param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('up','update','stop','status','prepare-model-storage','import-model','model-identity')]
    [string]$Action,
    [ValidateSet('frontend','backend','ingress','plot-executor','compute-worker')]
    [string[]]$Service = @(),
    [switch]$CheckOnly,
    [switch]$WithPlotting,
    [switch]$WithGpu,
    [switch]$WithIdentity,
    [switch]$WithCompute
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$identityConfiguration = Join-Path $projectRoot '.astroagent\container\deployment-v16.env'
$usingIdentity = $WithIdentity -or (Test-Path -LiteralPath $identityConfiguration)
$sharedModels = Join-Path $projectRoot '.astroagent\container\compose-v16-shared-model.yaml'
$computeOverlay = Join-Path $projectRoot 'compose.compute.yaml'
$mcpOverlay = Join-Path $projectRoot 'compose.mcp.yaml'
$v19Overlay = Join-Path $projectRoot 'compose.v19.yaml'
$v20Overlay = Join-Path $projectRoot 'compose.v20.yaml'
$configuration = if ($usingIdentity) { $identityConfiguration } else { Join-Path $projectRoot '.astroagent\container\deployment.env' }
if ((Test-Path -LiteralPath (Join-Path $projectRoot 'compose.identity.yaml')) -and -not $usingIdentity) {
    throw 'V1.6 source requires a separate identity deployment configuration. Do not rebuild the V1.5 tags with V1.6 source.'
}
if ($usingIdentity) { $WithPlotting = $true }
if (-not (Test-Path -LiteralPath $configuration)) { throw 'Prepare the separate container configuration first. See the V1.5 container guide.' }
$publicConfiguration = [System.IO.File]::ReadAllText($configuration)
$usingCompute = (Test-Path -LiteralPath $computeOverlay) -and ($WithCompute -or ($publicConfiguration -match '(?m)^COMPUTE_ENABLED=1\r?$'))
if ($Action -eq 'update') {
    if (-not $usingIdentity -or -not (Test-Path -LiteralPath $v20Overlay) -or -not $Service.Count) {
        throw 'Specify the changed services for the configured V2.0 local instance.'
    }
    $Service = @($Service | Select-Object -Unique)
} elseif ($Service.Count -or $CheckOnly) {
    throw '-Service and -CheckOnly are options for the update action.'
}
if ($Action -in @('up','update')) {
    foreach ($imageName in @('PYTHON_IMAGE','NODE_IMAGE','POSTGRES_IMAGE','OLLAMA_IMAGE','DOCKER_CLI_IMAGE')) {
        if ($publicConfiguration -notmatch ('(?m)^' + $imageName + '="[a-zA-Z0-9_./:-]+@sha256:[0-9a-f]{64}"\r?$')) { throw 'An immutable base image identity is missing. Prepare the image lock before building.' }
    }
}
$docker = (Get-Command docker.exe -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1).Source
if (-not $docker) { $docker = 'D:\Program Files\Docker\resources\bin\docker.exe' }
if (-not (Test-Path -LiteralPath $docker)) { throw 'Docker CLI is unavailable.' }
$localHost = if ($Action -eq 'update') { 'npipe:////./pipe/dockerDesktopLinuxEngine' } else { 'npipe:////./pipe/docker_engine' }
$dockerArguments = @('--host',$localHost)
$composeArguments = $dockerArguments + @('compose','--env-file',$configuration,'-f',(Join-Path $projectRoot 'compose.yaml'))
if ($Action -eq 'update') { $composeArguments += @('--project-name','astroagent-v16') }
if ($WithPlotting) { $composeArguments += @('-f',(Join-Path $projectRoot 'compose.plotting.yaml')) }
if ($WithGpu) { $composeArguments += @('-f',(Join-Path $projectRoot 'compose.gpu.yaml')) }
if ($usingIdentity) {
    $composeArguments += @('-f',(Join-Path $projectRoot 'compose.identity.yaml'))
    if (Test-Path -LiteralPath $sharedModels) { $composeArguments += @('-f',$sharedModels) }
}
if ($usingCompute) {
    $composeArguments += @('-f',$computeOverlay,'--profile','compute')
}
if (Test-Path -LiteralPath $mcpOverlay) {
    $composeArguments += @('-f',$mcpOverlay)
}
if (Test-Path -LiteralPath $v19Overlay) {
    $composeArguments += @('-f',$v19Overlay)
}
if (Test-Path -LiteralPath $v20Overlay) {
    $composeArguments += @('-f',$v20Overlay)
}

function Invoke-CheckedDocker([string[]]$Command) {
    & $docker @Command
    if ($LASTEXITCODE -ne 0) { throw "Local Docker command failed (exit $LASTEXITCODE)." }
}

function Invoke-LocalUpdate {
    $engine = Invoke-CheckedDocker ($dockerArguments + @('info','--format','{{.OSType}}/{{.OperatingSystem}}'))
    if ($engine -cne 'linux/Docker Desktop') { throw 'Select the local Docker Desktop Linux engine.' }

    try {
        $effective = (Invoke-CheckedDocker ($composeArguments + @('config','--format','json')) |
            Out-String) | ConvertFrom-Json
    } catch { throw 'Cannot resolve the local Compose project. Check the existing private configuration.' }
    $web = @($effective.services.ingress.ports)
    $databaseMount = @($effective.services.postgres.volumes | Where-Object {
        $_.type -eq 'volume' -and $_.source -eq 'postgres_data' -and
        $_.target -eq '/var/lib/postgresql/data'
    })
    if ($effective.name -cne 'astroagent-v16' -or $databaseMount.Count -ne 1 -or
        $effective.volumes.postgres_data.name -cne 'astroagent-v16_postgres_data' -or
        $web.Count -ne 1 -or $web[0].host_ip -cne '127.0.0.1' -or $web[0].published -ne '5173') {
        throw 'The resolved project does not match the established local database and 5173 entry point.'
    }
    foreach ($name in $Service) {
        if (-not $effective.services.$name.build -or ($name -eq 'compute-worker' -and -not $usingCompute)) {
            throw "The requested service is unavailable in the configured local project: $name"
        }
    }

    $resume = @()
    $containerIds = @{}
    foreach ($name in @('postgres','ollama','backend','frontend','ingress')) {
        $ids = @(Invoke-CheckedDocker ($composeArguments + @('ps','--all','-q',$name)))
        if ($ids.Count -ne 1) { throw "Expected one existing local $name container. Inspect project status first." }
        $containerIds[$name] = $ids[0]
        $state = Invoke-CheckedDocker ($dockerArguments + @('inspect','--format','{{.State.Status}}',$ids[0]))
        if ($state -notin @('running','exited','created')) { throw "Unexpected local service state: $name ($state)." }
        if ($state -ne 'running' -and $name -notin $Service) { $resume += $name }
    }
    $actualMounts = @(Invoke-CheckedDocker ($dockerArguments + @('inspect','--format',
        '{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Destination}}{{println}}{{end}}',$containerIds['postgres'])))
    if ('volume|astroagent-v16_postgres_data|/var/lib/postgresql/data' -notin $actualMounts) {
        throw 'The existing PostgreSQL container does not mount the expected local database volume.'
    }
    $database = $effective.services.backend.environment.ASTROAGENT_CONTAINER_DATABASE
    $currentDatabase = @(Invoke-CheckedDocker ($dockerArguments + @('inspect','--format',
        '{{range .Config.Env}}{{println .}}{{end}}',$containerIds['backend'])) |
        Where-Object { $_ -clike 'ASTROAGENT_CONTAINER_DATABASE=*' })
    if ($database -cnotmatch '^[a-z][a-z0-9_]{0,62}$' -or
        $currentDatabase.Count -ne 1 -or $currentDatabase[0] -cne "ASTROAGENT_CONTAINER_DATABASE=$database") {
        throw 'The requested backend database differs from the running local configuration.'
    }
    Write-Host "Local project astroagent-v16, database $database, entry http://127.0.0.1:5173"
    Write-Host "Services to build and update: $($Service -join ', ')"
    if ($CheckOnly) { return }

    Invoke-CheckedDocker ($composeArguments + @('build') + $Service)
    $storageToStart = @($resume | Where-Object { $_ -in @('postgres','ollama') })
    if ($storageToStart.Count) {
        Invoke-CheckedDocker ($composeArguments + @('start','--wait','--wait-timeout','120') + $storageToStart)
    }
    if ($usingCompute -and ('backend' -in $Service -or 'compute-worker' -in $Service)) {
        $active = Invoke-CheckedDocker ($composeArguments + @('exec','-T','postgres','psql',
            '-XAtq','-v','ON_ERROR_STOP=1','-U','postgres','-d',$database,'-c',
            "SELECT count(*) FROM public.compute_tasks WHERE state IN ('running','cancelling')"))
        if ($active -ne '0') { throw 'Wait for active local computations to finish before replacing the service.' }
    }

    $previousWorkerImage = $env:COMPUTE_IMAGE_ID
    try {
        if ('compute-worker' -in $Service) {
            $env:COMPUTE_IMAGE_ID = Invoke-CheckedDocker ($dockerArguments + @('image','inspect',
                '--format','{{.Id}}',$effective.services.'compute-worker'.image))
        }
        Invoke-CheckedDocker ($composeArguments + @('up','-d','--no-deps','--no-build','--pull','never',
            '--wait','--wait-timeout','120') + $Service)
    } finally { $env:COMPUTE_IMAGE_ID = $previousWorkerImage }

    $webToStart = @($resume | Where-Object { $_ -notin @('postgres','ollama') })
    if ($webToStart.Count) {
        Invoke-CheckedDocker ($composeArguments + @('start','--wait','--wait-timeout','120') + $webToStart)
    }
    foreach ($path in @('/login','/api/v1/auth/csrf')) {
        $curlArguments = @('--noproxy','*','--silent','--show-error','--output','NUL',
            '--write-out','%{http_code}','--max-time','8',"http://127.0.0.1:5173$path")
        $status = & curl.exe @curlArguments
        if ($LASTEXITCODE -ne 0 -or $status -ne '200') { throw "The local entry check failed: $path ($status)." }
    }
    Invoke-CheckedDocker ($composeArguments + @('ps'))
    Write-Host 'Update complete. Refresh http://127.0.0.1:5173.'
}

switch ($Action) {
    'up' {
        # Prepare only this Compose project's model volume before starting the non-root service.
        if (-not ($usingIdentity -and (Test-Path -LiteralPath $sharedModels))) {
            $prepareArguments = $composeArguments + @('--profile','tools','run','--rm','--no-deps','prepare-model-storage')
            & $docker @prepareArguments
            if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the dedicated model volume; existing data volumes were retained.' }
        }
        $composeArguments += @('up','-d','--build')
    }
    'stop' { $composeArguments += @('stop') }
    'status' { $composeArguments += @('ps') }
    'prepare-model-storage' { $composeArguments += @('--profile','tools','run','--rm','--no-deps','prepare-model-storage') }
    'import-model' { $composeArguments += @('--profile','tools','run','--rm','--no-deps','import-model') }
    'model-identity' {
        $identityScript = 'import json,urllib.request; values=json.load(urllib.request.urlopen("http://ollama:11434/api/tags",timeout=5))["models"]; item=next(v for v in values if v["name"]=="astroagent-qwen3-4b-instruct-2507:q4km"); print(json.dumps({key:item[key] for key in ("name","digest","size","details")},ensure_ascii=False))'
        $composeArguments += @('exec','-T','backend','python','-')
    }
}
Push-Location -LiteralPath $projectRoot
try {
    if ($Action -eq 'update') {
        $updateLock = New-Object Threading.Mutex($false, 'Global\AstroAgentLocalUpdate')
        $hasLock = $false
        try {
            try { $hasLock = $updateLock.WaitOne(0) }
            catch [Threading.AbandonedMutexException] { $hasLock = $true }
            if (-not $hasLock) { throw 'Another local application update is in progress.' }
            Invoke-LocalUpdate
        } finally {
            if ($hasLock) { $updateLock.ReleaseMutex() }
            $updateLock.Dispose()
        }
    } else {
        if ($Action -eq 'model-identity') { $identityScript | & $docker @composeArguments }
        else { & $docker @composeArguments }
        if ($LASTEXITCODE -ne 0) { throw 'Container operation did not complete. Existing data volumes were retained.' }
    }
} finally { Pop-Location }
