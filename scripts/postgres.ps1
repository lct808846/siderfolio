param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$standardRecord = Join-Path $projectRoot '.astroagent\postgres-standard\installation.json'
if (Test-Path -LiteralPath $standardRecord) {
    $standard = Get-Content -LiteralPath $standardRecord -Raw | ConvertFrom-Json
    if ($standard.status -eq 'complete') {
        $service = Get-Service -Name $standard.service
        if ($Action -eq 'status') {
            $service | Select-Object Name, Status, StartType
            Write-Output ('Data: ' + $standard.data_directory)
            exit 0
        }
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'Windows service start/stop requires an administrator PowerShell window.'
        }
        if ($Action -eq 'start') {
            Start-Service -Name $standard.service
        } else {
            Stop-Service -Name $standard.service
        }
        Get-Service -Name $standard.service | Select-Object Name, Status, StartType
        exit 0
    }
}
$runtimeBin = Join-Path $projectRoot '.astroagent\postgres-runtime\Library\bin'
$clusterData = Join-Path $projectRoot '.astroagent\postgres\data'
$serverLog = Join-Path $projectRoot '.astroagent\postgres\server.log'
$controller = Join-Path $runtimeBin 'pg_ctl.exe'
if (-not (Test-Path -LiteralPath $controller) -or -not (Test-Path -LiteralPath (Join-Path $clusterData 'PG_VERSION'))) {
    throw '本项目的PostgreSQL环境或数据目录尚未准备好；不会创建或覆盖数据库。'
}
$env:PATH = "$runtimeBin;$env:PATH"
if ($Action -eq 'start') {
    & $controller -D $clusterData status *> $null
    if ($LASTEXITCODE -eq 0) { Write-Output '本项目的PostgreSQL已经运行。'; exit 0 }
    & $controller -D $clusterData -l $serverLog -w -t 30 start
} elseif ($Action -eq 'stop') {
    & $controller -D $clusterData -m fast -w -t 30 stop
} else {
    & $controller -D $clusterData status
}
exit $LASTEXITCODE
