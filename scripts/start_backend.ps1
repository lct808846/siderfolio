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
$env:TEMP = Join-Path $runtimeRoot 'temp'
$env:TMP = $env:TEMP
$env:HF_HOME = Join-Path $runtimeRoot 'cache\huggingface'
$env:TORCH_HOME = Join-Path $runtimeRoot 'cache\torch'
$env:XDG_CACHE_HOME = Join-Path $runtimeRoot 'cache'
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
