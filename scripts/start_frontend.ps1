param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 5173,
    [string]$NodeBinary = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $NodeBinary) {
    $NodeBinary = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
}
if (-not (Test-Path -LiteralPath $NodeBinary)) {
    throw 'The Node 24 runtime was not found. Pass -NodeBinary with its absolute path.'
}
$previousCI = $env:CI
# Vite otherwise exits when a detached launcher's stdin closes. This starts no tests.
$env:CI = 'true'
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    & $NodeBinary 'node_modules\vite\bin\vite.js' --host 127.0.0.1 --port $Port --strictPort
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    $env:CI = $previousCI
}
exit $code
