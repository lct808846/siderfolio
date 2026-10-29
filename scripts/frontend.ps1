param(
    [ValidateSet('dev', 'build', 'serve')]
    [string]$Mode = 'serve',
    [string]$NodePath = ''
)
$ErrorActionPreference = 'Stop'
$frontendRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend'
$nodeExe = $NodePath
if (-not $nodeExe) { $nodeExe = (Get-Command node.exe -ErrorAction Stop).Source }
function Test-SupportedNode([string]$Candidate) {
    if (-not (Test-Path -LiteralPath $Candidate)) { return $false }
    $runtimeVersion = [version]((& $Candidate --version).Trim().TrimStart('v'))
    return $runtimeVersion.Major -eq 24 -and $runtimeVersion.Minor -ge 15
}
if (-not (Test-SupportedNode $nodeExe)) {
    $bundledNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
    if ($NodePath -or -not (Test-SupportedNode $bundledNode)) {
        throw 'Node.js 24.15+ (24.x) is required. Install a supported Node version or pass -NodePath.'
    }
    $nodeExe = $bundledNode
}
$npmExecutable = (Get-Command npm.cmd -ErrorAction Stop).Source
$npmCli = Join-Path (Split-Path -Parent $npmExecutable) 'node_modules\npm\bin\npm-cli.js'
if (-not (Test-Path -LiteralPath $npmCli)) { throw 'npm CLI was not found beside npm.cmd.' }
$previousPath = $env:PATH
Push-Location $frontendRoot
try {
    $env:PATH = (Split-Path -Parent $nodeExe) + ';' + $env:PATH
    Write-Host ('Using Node ' + (& $nodeExe --version))
    if (-not (Test-Path -LiteralPath 'node_modules')) {
        & $nodeExe $npmCli ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    }
    if ($Mode -eq 'serve' -and -not (Test-Path -LiteralPath 'dist/index.html')) {
        & $nodeExe $npmCli run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    }
    & $nodeExe $npmCli run $Mode
    if ($LASTEXITCODE -ne 0) { throw ('Frontend command failed: ' + $Mode) }
}
finally {
    $env:PATH = $previousPath
    Pop-Location
}
