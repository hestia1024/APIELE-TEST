$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    throw 'Fill SSH_HOST in .env first, then run this script again.'
}
$taskConfig = @{}
foreach ($taskLine in Get-Content -LiteralPath '.env' -Encoding utf8) {
    if ($taskLine -match '^\s*([A-Z_]+)\s*=\s*(.*?)\s*$') {
        $taskConfig[$Matches[1]] = $Matches[2].Trim('"', "'")
    }
}
if (-not $taskConfig['SSH_HOST']) { throw 'Fill SSH_HOST in .env first.' }
$taskSshPort = if ($taskConfig['SSH_PORT']) { [int]$taskConfig['SSH_PORT'] } else { 22 }
$taskLocalPort = if ($taskConfig['DB_PORT']) { [int]$taskConfig['DB_PORT'] } else { 13307 }
$taskRemotePort = if ($taskConfig['SSH_REMOTE_DB_PORT']) { [int]$taskConfig['SSH_REMOTE_DB_PORT'] } else { 3307 }
$taskSshUser = if ($taskConfig['SSH_USER']) { $taskConfig['SSH_USER'] } else { 'root' }
$taskDestination = '{0}@{1}' -f $taskSshUser, $taskConfig['SSH_HOST']
$taskForward = '127.0.0.1:{0}:127.0.0.1:{1}' -f $taskLocalPort, $taskRemotePort
Write-Host "Opening MySQL SSH tunnel on 127.0.0.1:$taskLocalPort. Keep this terminal open."
& ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L $taskForward -p $taskSshPort $taskDestination
if ($LASTEXITCODE -ne 0) { throw 'SSH tunnel failed. Check the SSH error above.' }
