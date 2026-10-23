# Start Playnext on this PC for local development (http://127.0.0.1:8000 only).
# The public site runs on the Linux server instead (scripts/deploy.ps1, scripts/deploy/playnext.service).
# Usage: pwsh -File scripts/serve.ps1   or double-click start.bat
# (starts Docker Desktop and the playnext-db container when needed; Ctrl+C stops)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$port = 8000

if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    throw "port $port is already in use; Playnext is probably running already (http://127.0.0.1:$port)"
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'web\dist\index.html'))) {
    Write-Warning 'web/dist is missing, so only the API will be served; build it with: npm --prefix web run build'
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    if (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue) {
        Write-Host 'Waiting for Docker Desktop to finish starting...'
    } else {
        Write-Host 'Starting Docker Desktop...'
        Start-Process -FilePath (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
    }
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 3
        & docker info *> $null
    } until ($LASTEXITCODE -eq 0 -or (Get-Date) -gt $deadline)
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop did not start within 3 minutes' }
}

& docker inspect playnext-db *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Creating the playnext-db container...'
    & docker compose --project-directory $root up -d
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }
}

# The container has restart: unless-stopped, so a freshly started engine starts it by itself. A docker start
# racing that start fails with "ports are not available", so judge by the container state, not by the exit code.
$deadline = (Get-Date).AddSeconds(45)
while ((& docker inspect -f '{{.State.Running}}' playnext-db) -ne 'true') {
    if ((Get-Date) -gt $deadline) { throw 'could not start the playnext-db container (see: docker logs playnext-db)' }
    & docker start playnext-db *> $null
    Start-Sleep -Seconds 2
}

$deadline = (Get-Date).AddMinutes(2)
while (($health = & docker inspect -f '{{.State.Health.Status}}' playnext-db) -ne 'healthy') {
    if ((Get-Date) -gt $deadline) { throw "database is not healthy after 2 minutes (status: $health)" }
    Start-Sleep -Seconds 2
}
Write-Host 'Database: healthy'

# an activated conda env would only make uv print a warning; the project always runs in .venv
$env:VIRTUAL_ENV = $null
Write-Host "Starting Playnext on port $port (ready when ""Application startup complete"" appears)..."
& uv --directory $root run uvicorn --app-dir src playnext.api:app --host 127.0.0.1 --port $port
exit $LASTEXITCODE
