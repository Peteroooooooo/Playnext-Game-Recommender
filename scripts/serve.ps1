# Start Playnext for local use and for a public reverse proxy on another server.
# The public entry is nginx on a separate server, which reaches this PC over a private EasyTier subnet (10.10.10.0/24);
# --proxy-headers makes the Steam login return to the public domain instead of this PC's address.
# Usage: pwsh -File scripts/serve.ps1   (starts Docker Desktop and the playnext-db container when needed; Ctrl+C stops)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Starting Docker Desktop...'
    Start-Process -FilePath 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 3
        & docker info *> $null
    } until ($LASTEXITCODE -eq 0 -or (Get-Date) -gt $deadline)
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop did not start within 3 minutes' }
}

& docker start playnext-db | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'could not start the playnext-db container' }
$deadline = (Get-Date).AddMinutes(1)
do {
    Start-Sleep -Seconds 2
    $health = & docker inspect -f '{{.State.Health.Status}}' playnext-db
} until ($health -eq 'healthy' -or (Get-Date) -gt $deadline)
Write-Host "Database: $health"

Write-Host 'Starting Playnext on port 8000 (ready when "Application startup complete" appears)...'
& uv --directory $root run uvicorn --app-dir src playnext.api:app --host 0.0.0.0 --port 8000 `
    --proxy-headers --forwarded-allow-ips '127.0.0.1,10.10.10.40'
exit $LASTEXITCODE
