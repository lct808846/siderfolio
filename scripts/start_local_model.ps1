param([string]$OllamaBinary = 'D:\astroagent-runtime\ollama\ollama.exe')
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $OllamaBinary)) { throw 'Install Ollama from the prepared signed installer first.' }
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = 'D:\astroagent-models\ollama'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_MAX_QUEUE = '2'
$env:OLLAMA_CONTEXT_LENGTH = '8192'
$env:OLLAMA_KEEP_ALIVE = '30s'
$env:TEMP = 'D:\astroagent-runtime\temp\ollama'
$env:TMP = $env:TEMP
foreach ($privateName in @('DEEPSEEK_API_KEY','ADS_API_TOKEN','ASTROAGENT_DATABASE_URL')) {
    [Environment]::SetEnvironmentVariable($privateName, $null, 'Process')
}
New-Item -ItemType Directory -Path $env:OLLAMA_MODELS,$env:TEMP -Force | Out-Null
& $OllamaBinary serve
exit $LASTEXITCODE
