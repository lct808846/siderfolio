param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('up','stop','status','prepare-model-storage','import-model','model-identity')]
    [string]$Action,
    [switch]$WithPlotting,
    [switch]$WithGpu
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$configuration = Join-Path $projectRoot '.astroagent\container\deployment.env'
if (-not (Test-Path -LiteralPath $configuration)) { throw 'Prepare the separate container configuration first. See the V1.5 container guide.' }
if ($Action -eq 'up') {
    $publicConfiguration = [System.IO.File]::ReadAllText($configuration)
    foreach ($imageName in @('PYTHON_IMAGE','NODE_IMAGE','POSTGRES_IMAGE','OLLAMA_IMAGE','DOCKER_CLI_IMAGE')) {
        if ($publicConfiguration -notmatch ('(?m)^' + $imageName + '="[a-zA-Z0-9_./:-]+@sha256:[0-9a-f]{64}"\r?$')) { throw 'An immutable base image identity is missing. Prepare the image lock before building.' }
    }
}
$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) { $docker = 'D:\Program Files\Docker\resources\bin\docker.exe' }
if (-not (Test-Path -LiteralPath $docker)) { throw 'Docker CLI is unavailable.' }
$composeArguments = @('--host','npipe:////./pipe/docker_engine','compose','--env-file',$configuration,'-f',(Join-Path $projectRoot 'compose.yaml'))
if ($WithPlotting) { $composeArguments += @('-f',(Join-Path $projectRoot 'compose.plotting.yaml')) }
if ($WithGpu) { $composeArguments += @('-f',(Join-Path $projectRoot 'compose.gpu.yaml')) }
switch ($Action) {
    'up' {
        # Prepare only this Compose project's model volume before starting the non-root service.
        $prepareArguments = $composeArguments + @('--profile','tools','run','--rm','--no-deps','prepare-model-storage')
        & $docker @prepareArguments
        if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the dedicated model volume; existing data volumes were retained.' }
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
    if ($Action -eq 'model-identity') { $identityScript | & $docker @composeArguments }
    else { & $docker @composeArguments }
    if ($LASTEXITCODE -ne 0) { throw 'Container operation did not complete. Existing data volumes were retained.' }
} finally { Pop-Location }
