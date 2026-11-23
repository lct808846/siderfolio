[CmdletBinding()]
param(
    [ValidateSet('Update', 'Start', 'Status', 'Logs', 'Stop', 'Account', 'InitCompute', 'BuildPlot', 'Config')]
    [string]$Action = 'Update',
    [ValidateSet('frontend', 'backend', 'postgres', 'compute-worker', 'ollama')]
    [string]$Service,
    [ValidateSet('frontend', 'backend', 'compute-worker')]
    [string[]]$Rebuild = @(),
    [ValidateSet('python', 'gnuplot', 'executor')]
    [string[]]$PlotImage = @('python', 'gnuplot', 'executor')
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$projectName = 'astroagent-dev'
$devDirectory = Join-Path $repo '.astroagent/dev'
$runtime = Join-Path $devDirectory 'runtime.env'
$settingsPath = Join-Path $repo '.env.dev'
$ownerLabel = 'io.astroagent.dev.workspace'
$dockerExe = (Get-Command docker.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$dockerArgs = @('--host', 'npipe:////./pipe/dockerDesktopLinuxEngine')
$preview = 'http://127.0.0.1:15273'

function SHA256([string]$Value) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))).Replace('-', '').ToLowerInvariant()
    } finally { $algorithm.Dispose() }
}

function New-RandomBytes {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $bytes = New-Object byte[] 32
        $rng.GetBytes($bytes)
        return ,$bytes
    } finally { $rng.Dispose() }
}

function New-LocalToken {
    $bytes = New-RandomBytes
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
}

function Invoke-DevDocker([string[]]$Arguments) {
    & $dockerExe @dockerArgs @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker development command failed (exit $LASTEXITCODE)." }
}

function Invoke-DevCompose([string[]]$Arguments) {
    Invoke-DevDocker ($composeArgs + $Arguments)
}

function Get-InputKey([string[]]$Paths, $Build) {
    $inputs = foreach ($path in ($Paths | Sort-Object -Unique)) {
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $repo $path)).Hash
        "$path=$hash"
    }
    (SHA256 (($inputs -join "`n") + (ConvertTo-Json -Depth 12 -Compress -InputObject $Build))).Substring(0, 20)
}

function Get-DevSetting([string]$Name, [string]$Fallback = '') {
    if ($settings.ContainsKey($Name)) { return $settings[$Name] }
    return $Fallback
}

function Read-DevSettings {
    $allowed = @('ASTRO_DEV_COMPUTE', 'ASTRO_DEV_EMBEDDING_DIR', 'ASTRO_DEV_EMBEDDING_SHA256',
        'ASTRO_DEV_OLLAMA_MODELS_DIR', 'ASTRO_DEV_OLLAMA_IMAGE', 'ASTRO_DEV_OLLAMA_DIGEST')
    $result = @{}
    if (Test-Path -LiteralPath $settingsPath) {
        foreach ($line in [IO.File]::ReadAllLines($settingsPath)) {
            if ($line -match '^\s*(#|$)') { continue }
            if ($line -notmatch '^(ASTRO_DEV_[A-Z_0-9]+)=([^\r\n]*)$' -or
                $Matches[1] -cnotin $allowed -or $result.ContainsKey($Matches[1])) {
                throw '.env.dev contains an unsupported or duplicate development setting.'
            }
            $result[$Matches[1]] = $Matches[2].Trim()
        }
    }
    return $result
}

function Set-ModelDirectory([string]$Name) {
    $value = Get-DevSetting $Name
    if (-not $value) { return $false }
    if ($value -notmatch '^[a-zA-Z]:/[^$`r`n]+$' -or
        -not (Test-Path -LiteralPath $value -PathType Container)) {
        throw "$Name must identify an existing local model directory such as D:/models/embedding."
    }
    [Environment]::SetEnvironmentVariable($Name, $value, 'Process')
    return $true
}

function Get-DevContainers {
    @(Invoke-DevDocker @('ps', '-aq', '--filter', "label=com.docker.compose.project=$projectName"))
}

function Confirm-DevResource([string]$Type, [string]$Id) {
    $labelPath = if ($Type -eq 'container') { '.Config.Labels' } else { '.Labels' }
    $result = Invoke-DevDocker @($Type, 'inspect', '--format', "{{index $labelPath `"$ownerLabel`"}}", $Id)
    if ($result -cne $owner) {
        throw "The Docker development project contains a $Type owned by another workspace or unknown setup."
    }
}

function Invoke-DevSql([string]$Sql) {
    Invoke-DevCompose @('exec', '-T', 'postgres', 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1',
        '-U', 'postgres', '-d', 'astroagent_dev', '-c', $Sql)
}

function Get-DevServiceIds([string]$Target) {
    @(Invoke-DevCompose @('ps', '-aq', $Target))
}

function Confirm-ComputeIdle {
    if (-not (Get-DevServiceIds 'compute-worker')) { return }
    if ((Invoke-DevSql "SELECT to_regclass('public.compute_tasks') IS NOT NULL") -ne 't' -or
        (Invoke-DevSql "SELECT EXISTS (SELECT 1 FROM public.compute_tasks WHERE state IN ('queued','running','cancelling'))") -ne 'f') {
        throw 'Wait for development compute tasks to finish before updating or stopping the worker.'
    }
}

function Ensure-DevImage([string]$Target, [string]$Reference) {
    $exists = @(Invoke-DevDocker @('image', 'ls', '--quiet', '--filter', "reference=$Reference"))
    if ($Target -in $Rebuild -or $exists.Count -eq 0) {
        Write-Host "Building development image: $Target"
        Invoke-DevCompose @('build', $Target)
    } else { Write-Host "Using cached development image: $Target" }
}

function Confirm-DevConfig($Config) {
    if ($Config.name -ne $projectName -or
        $Config.services.postgres.environment.POSTGRES_DB -ne 'astroagent_dev' -or
        $Config.services.backend.environment.ASTROAGENT_DATABASE_URL -cnotmatch
            '^postgresql://astroagent:[a-f0-9]{64}@postgres:5432/astroagent_dev$' -or
        $Config.services.postgres.volumes[0].source -ne 'postgres_data' -or
        $Config.volumes.postgres_data.name -ne 'astroagent-dev_postgres_data') {
        throw 'The Compose configuration does not match the isolated development database.'
    }
    foreach ($resource in @($Config.volumes.PSObject.Properties) + @($Config.networks.PSObject.Properties)) {
        $spec = $resource.Value
        if ($spec.external -or $spec.name -cne "${projectName}_$($resource.Name)" -or
            $spec.labels.$ownerLabel -cne $owner) {
            throw 'The development Compose project must use its own named networks and volumes.'
        }
    }
    foreach ($entry in $Config.services.PSObject.Properties) {
        $spec = $entry.Value
        if ($spec.labels.$ownerLabel -cne $owner -or $spec.privileged -or $spec.container_name -or
            $spec.use_api_socket -or $spec.network_mode -notin @($null, 'none')) {
            throw 'A development service has an unexpected identity, network or permission.'
        }
        foreach ($volume in $spec.volumes) {
            if ($volume.type -eq 'bind' -and (-not $volume.read_only -or
                $volume.source -match '(?i)(docker\.sock|docker_engine)' -or
                $volume.target -match '(?i)(docker\.sock|docker_engine)')) {
                throw 'Development bind mounts must be read-only and exclude Docker control interfaces.'
            }
        }
        foreach ($port in $spec.ports) {
            if ($entry.Name -ne 'frontend' -or $port.host_ip -cne '127.0.0.1' -or
                $port.published -ne '15273' -or $port.target -ne 5173) {
                throw 'Only the loopback Vite preview port may be published.'
            }
        }
    }
}

$owner = SHA256 $repo.ToLowerInvariant()
$inherited = @{}
$lock = $null
$locked = $false
try {
    foreach ($item in (Get-ChildItem Env: | Where-Object {
        $_.Name -match '^(ASTRO_DEV_|COMPOSE_|DOCKER_(HOST|CONTEXT|TLS|TLS_VERIFY|CERT_PATH)$)'
    })) {
        $inherited[$item.Name] = $item.Value
        [Environment]::SetEnvironmentVariable($item.Name, $null, 'Process')
    }

    if ($Action -ne 'Config') {
        $lock = New-Object Threading.Mutex($false, 'Global\AstroAgentDevDocker')
        try { $locked = $lock.WaitOne(0) }
        catch [Threading.AbandonedMutexException] { $locked = $true }
        if (-not $locked) { throw 'Another development update is already running.' }
        $engine = Invoke-DevDocker @('info', '--format', '{{.OSType}}/{{.OperatingSystem}}')
        if ($engine -ne 'linux/Docker Desktop') {
            throw 'Use the local Linux engine in Windows Docker Desktop.'
        }
        foreach ($id in (Get-DevContainers)) { Confirm-DevResource 'container' $id }
        $volumes = @(Invoke-DevDocker @('volume', 'ls', '--format', '{{.Name}}') |
            Where-Object { $_.StartsWith("${projectName}_") })
        $networks = @(Invoke-DevDocker @('network', 'ls', '--format', '{{.Name}}') |
            Where-Object { $_.StartsWith("${projectName}_") })
        foreach ($id in $volumes) { Confirm-DevResource 'volume' $id }
        foreach ($id in $networks) { Confirm-DevResource 'network' $id }
    }

    if ($Action -in @('Status', 'Logs', 'Stop', 'Account', 'InitCompute') -and
        -not (Test-Path -LiteralPath $runtime -PathType Leaf)) {
        throw 'No configured development stack. Run scripts/dev.ps1 -Action Start first.'
    }
    if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {
        if ($Action -ne 'Config' -and $volumes.Count) {
            throw 'Restore the development runtime.env associated with the existing development volumes.'
        }
        if ($Action -eq 'Config') {
            $env:ASTRO_DEV_PG_PASSWORD = 'fixture-' + ('0' * 64)
            $env:ASTRO_DEV_DB_PASSWORD = '0' * 64
            $env:ASTRO_DEV_PROXY_TOKEN = '1' * 64
            $env:ASTRO_DEV_AUTH_SECRET = ('A' * 43) + '='
        }
    }
    $settings = Read-DevSettings
    $compute = Get-DevSetting 'ASTRO_DEV_COMPUTE' '0'
    if ($compute -cnotin @('0', '1')) { throw 'ASTRO_DEV_COMPUTE must be 0 or 1.' }
    $env:ASTRO_DEV_COMPUTE = $compute
    $rag = Set-ModelDirectory 'ASTRO_DEV_EMBEDDING_DIR'
    $ollama = Set-ModelDirectory 'ASTRO_DEV_OLLAMA_MODELS_DIR'
    if ($rag) {
        $embeddingChecksum = Get-DevSetting 'ASTRO_DEV_EMBEDDING_SHA256'
        if ($embeddingChecksum -cnotmatch '^[a-f0-9]{64}$') { throw 'Set the verified embedding SHA-256.' }
        $env:ASTRO_DEV_EMBEDDING_SHA256 = $embeddingChecksum
        $env:ASTRO_DEV_RAG_ENABLED = 'true'
    }
    if ($ollama) {
        $ollamaImage = Get-DevSetting 'ASTRO_DEV_OLLAMA_IMAGE'
        $ollamaDigest = Get-DevSetting 'ASTRO_DEV_OLLAMA_DIGEST'
        if ($ollamaImage -cnotmatch '^ollama/ollama@sha256:[a-f0-9]{64}$' -or
            $ollamaDigest -cnotmatch '^(sha256:)?[a-f0-9]{64}$') {
            throw 'Set the pinned Ollama image and the verified Qwen model digest.'
        }
        $env:ASTRO_DEV_OLLAMA_IMAGE = $ollamaImage
        $env:ASTRO_DEV_OLLAMA_DIGEST = $ollamaDigest
        $env:ASTRO_DEV_OLLAMA_ENABLED = 'true'
    }

    $backendPaths = @('containers/application/Dockerfile', 'containers/application/requirements-runtime.lock',
        'pyproject.toml', '.dockerignore')
    $workerPaths = @(Get-ChildItem (Join-Path $repo 'src/astroagent') -Filter 'compute*.py' -File |
        ForEach-Object { "src/astroagent/$($_.Name)" })
    $env:ASTRO_DEV_OWNER = $owner
    $env:ASTRO_DEV_BACKEND_KEY = 'config'
    $env:ASTRO_DEV_FRONTEND_KEY = 'config'
    $env:ASTRO_DEV_WORKER_KEY = 'config'

    $composeArgs = @('compose', '--project-name', $projectName, '--project-directory', $repo,
        '-f', (Join-Path $repo 'compose.dev.yaml'), '--profile', 'compute', '--profile', 'ollama')
    if ($Action -eq 'Config') {
        $inputFile = if (Test-Path -LiteralPath $runtime) { $runtime } else { Join-Path $repo '.env.dev.example' }
        Invoke-DevCompose @('--env-file', $inputFile, 'config', '--quiet')
        return
    }

    New-Item -ItemType Directory -Path (Join-Path $devDirectory 'empty-models') -Force | Out-Null
    if (-not (Test-Path -LiteralPath $runtime)) {
        $identity = [Convert]::ToBase64String((New-RandomBytes)).Replace('+', '-').Replace('/', '_')
        $lines = @("ASTRO_DEV_PG_PASSWORD=$(New-LocalToken)", "ASTRO_DEV_DB_PASSWORD=$(New-LocalToken)",
            "ASTRO_DEV_PROXY_TOKEN=$(New-LocalToken)", "ASTRO_DEV_AUTH_SECRET=$identity")
        $writer = New-Object IO.StreamWriter([IO.File]::Open($runtime, 'CreateNew', 'Write', 'None'))
        try { $writer.WriteLine($lines -join "`n") } finally { $writer.Dispose() }
    }
    $composeArgs += @('--env-file', $runtime)
    try {
        $effective = (Invoke-DevCompose @('config', '--format', 'json') | Out-String) | ConvertFrom-Json
    } catch { throw 'Could not read the development Compose configuration.' }
    Confirm-DevConfig $effective
    $env:ASTRO_DEV_BACKEND_KEY = Get-InputKey $backendPaths $effective.services.backend.build
    $env:ASTRO_DEV_FRONTEND_KEY = Get-InputKey @('frontend/package.json', 'frontend/package-lock.json',
        'containers/frontend/Dockerfile', '.dockerignore') $effective.services.frontend.build
    $env:ASTRO_DEV_WORKER_KEY = Get-InputKey ($backendPaths + $workerPaths +
        @('containers/application/requirements-compute.lock', 'src/astroagent/__init__.py')) $effective.services.'compute-worker'.build

    switch ($Action) {
        'Status' { Invoke-DevCompose @('ps', '-a'); Write-Host "Preview: $preview"; return }
        'Logs' {
            $command = @('logs', '--tail', '100')
            if ($Service) { $command += $Service }
            Invoke-DevCompose $command
            return
        }
        'Stop' {
            if (-not $Service -or $Service -eq 'compute-worker') { Confirm-ComputeIdle }
            $command = @('stop')
            if ($Service) { $command += $Service }
            Invoke-DevCompose $command
            return
        }
        'Account' {
            Invoke-DevCompose @('exec', '-T', 'backend', 'python', '/devtools/dev_identity.py')
            return
        }
        'InitCompute' {
            if ($compute -ne '1') { throw 'Enable ASTRO_DEV_COMPUTE=1 in .env.dev first.' }
            if ((Invoke-DevSql "SELECT to_regclass('public.compute_tasks') IS NOT NULL") -eq 't') {
                throw 'Development compute tables already exist. Update normally or review schema changes separately.'
            }
            Invoke-DevCompose @('exec', '-T', 'postgres', 'sh', '-ec',
                'PGPASSWORD="$ASTRO_DEV_DB_PASSWORD" exec psql -h 127.0.0.1 -U astroagent -d astroagent_dev -v ON_ERROR_STOP=1 -f /devtools/compute_schema.sql')
            Write-Host 'Development compute schema installed. Run Update.'
            return
        }
        'BuildPlot' {
            foreach ($engineName in $PlotImage) {
                if ($engineName -eq 'executor') {
                    $recipe = $effective.services.backend.build
                    Invoke-DevDocker @('build', '-f', (Join-Path $repo $recipe.dockerfile), '--target', 'executor',
                        '--build-arg', "PYTHON_IMAGE=$($recipe.args.PYTHON_IMAGE)",
                        '--build-arg', "DOCKER_CLI_IMAGE=$($recipe.args.DOCKER_CLI_IMAGE)",
                        '-t', 'astroagent-dev-plot-executor:local', $repo)
                } else {
                    Invoke-DevDocker @('build', '-f', (Join-Path $repo "containers/plotting/$engineName.Dockerfile"),
                        '-t', "astroagent-dev-plot-${engineName}:local", (Join-Path $repo 'containers/plotting'))
                }
            }
            Write-Host 'Plotting images built. Starting the plot broker requires an independent executor boundary.'
            return
        }
    }

    Invoke-DevCompose @('up', '-d', '--no-deps', '--wait', '--wait-timeout', '150', 'postgres')
    $schema = Invoke-DevSql "SELECT to_regclass('public.auth_meta') IS NOT NULL"
    Ensure-DevImage 'backend' "astroagent-dev-backend:$env:ASTRO_DEV_BACKEND_KEY"
    if ($schema -ne 't') {
        if ((Invoke-DevSql "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')") -ne '0') {
            throw 'The isolated database is not empty and has no identity schema. Review its data before continuing.'
        }
        Invoke-DevCompose @('run', '--rm', '--no-deps', 'backend', '-m', 'astroagent.identity_cli', 'initialize')
    }
    $services = @('backend', 'frontend')
    if ($compute -eq '1') {
        if ((Invoke-DevSql "SELECT to_regclass('public.compute_tasks') IS NOT NULL") -ne 't') {
            throw 'Run scripts/dev.ps1 -Action InitCompute before enabling the development worker.'
        }
        $workerRef = "astroagent-dev-compute:$env:ASTRO_DEV_WORKER_KEY"
        $worker = @(Get-DevServiceIds 'compute-worker')
        if ($worker.Count -gt 0) {
            $current = Invoke-DevDocker @('inspect', '--format', '{{.Config.Image}}', $worker[0])
            if ($current -ne $workerRef -or 'compute-worker' -in $Rebuild) { Confirm-ComputeIdle }
        }
        Ensure-DevImage 'compute-worker' $workerRef
        $env:ASTRO_DEV_WORKER_IMAGE_ID = Invoke-DevDocker @('image', 'inspect', '--format', '{{.Id}}', $workerRef)
        $services += 'compute-worker'
    } elseif (Get-DevServiceIds 'compute-worker') {
        Confirm-ComputeIdle
        Invoke-DevCompose @('stop', 'compute-worker')
    }
    if ($ollama) { $services += 'ollama' }
    elseif (Get-DevServiceIds 'ollama') { Invoke-DevCompose @('stop', 'ollama') }
    Ensure-DevImage 'frontend' "astroagent-dev-frontend:$env:ASTRO_DEV_FRONTEND_KEY"
    Invoke-DevCompose (@('up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '150') + $services)
    $null = Invoke-RestMethod -Uri "$preview/api/v1/auth/csrf" -TimeoutSec 10
    Invoke-DevCompose @('ps', '-a')
    Write-Host "Preview: $preview (Vue HMR / FastAPI reload for mounted source)"
} catch {
    Write-Error "Development update did not complete. $($_.Exception.Message)" -ErrorAction Continue
    exit 1
} finally {
    if ($locked) { $lock.ReleaseMutex() }
    if ($lock) { $lock.Dispose() }
    Get-ChildItem Env: | Where-Object { $_.Name -like 'ASTRO_DEV_*' } | ForEach-Object {
        [Environment]::SetEnvironmentVariable($_.Name, $null, 'Process')
    }
    foreach ($name in $inherited.Keys) {
        [Environment]::SetEnvironmentVariable($name, $inherited[$name], 'Process')
    }
}
