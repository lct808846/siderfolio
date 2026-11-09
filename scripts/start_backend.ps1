param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = 'D:\astroagent-runtime'
$python = Join-Path $runtimeRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'The D-drive RAG runtime is missing. See docs/development/v1.0.0/MODEL_SETUP.md.'
}
# Project provider settings must replace any legacy key inherited by this local launcher.
# Only clear provider variables explicitly declared in this project's .env; never print values.
$providerFile = Join-Path $projectRoot '.env'
if (Test-Path -LiteralPath $providerFile) {
    foreach ($providerLine in [System.IO.File]::ReadLines($providerFile)) {
        if ($providerLine -match '^\s*(?:export\s+)?(DEEPSEEK_API_KEY|DEEPSEEK_BASE_URL|DEEPSEEK_MODEL|CHAT_MODELS|LLM_THINKING_PARAMETER)\s*=') {
            [Environment]::SetEnvironmentVariable($Matches[1], $null, 'Process')
        }
    }
}
$env:TEMP = Join-Path $runtimeRoot 'temp'
$env:TMP = $env:TEMP
$env:HF_HOME = Join-Path $runtimeRoot 'cache\huggingface'
$env:TORCH_HOME = Join-Path $runtimeRoot 'cache\torch'
$env:XDG_CACHE_HOME = Join-Path $runtimeRoot 'cache'
$plotDockerBin = 'D:\Program Files\Docker\resources\bin'
if (Test-Path -LiteralPath (Join-Path $plotDockerBin 'docker.exe')) {
    # Existing terminal sessions may predate the D-drive Docker installation.
    $env:PATH = "$plotDockerBin;$env:PATH"
}
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
New-Item -ItemType Directory -Path $env:TEMP, $env:HF_HOME, $env:TORCH_HOME -Force | Out-Null
Push-Location -LiteralPath $projectRoot
try {
    & $python -m uvicorn astroagent.main:app --host 127.0.0.1 --port $Port --workers 1
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
