# Deploy Playnext to the Linux server over SSH: builds the web app, uploads the code and the ~44 MB of tables the
# service reads (README step 11) to /opt/playnext, then runs scripts/deploy/server.sh there (venv, PostgreSQL
# container, systemd unit, health check). The server's prices.parquet is kept once it exists, since the service
# refreshes it daily. .env is uploaded only with -CopyEnv.
# Usage: pwsh -File scripts/deploy.ps1 [-Server cubie] [-CopyEnv] [-SkipData] [-SkipWeb]
param([string]$Server = 'cubie', [switch]$CopyEnv, [switch]$SkipData, [switch]$SkipWeb)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dir = '/opt/playnext'

function Invoke-Native([string]$exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "$exe failed ($LASTEXITCODE): $($argv -join ' ')" }
}

if (-not $SkipWeb) { Invoke-Native 'npm' @('--prefix', (Join-Path $root 'web'), 'run', 'build') }

$items = @('src', 'scripts', 'pyproject.toml', 'uv.lock', 'web/dist')
if (-not $SkipData) {
    $hasPrices = (& ssh $Server "test -f $dir/data/processed/prices.parquet && echo yes") -eq 'yes'
    $items += Get-ChildItem -LiteralPath (Join-Path $root 'data/processed') -Filter '*.parquet' |
        Where-Object { $_.Name -notlike 'prices_backup_*' -and -not ($hasPrices -and $_.Name -eq 'prices.parquet') } |
        ForEach-Object { "data/processed/$($_.Name)" }
    $items += @('data/derived/neighbors_k200.npz', 'data/derived/colike_reviews100m.parquet',
                'data/derived/playtime_reference_100m.parquet', 'data/raw/itad/id_map.json')
}

$tgz = Join-Path ([IO.Path]::GetTempPath()) "playnext-deploy-$PID.tgz"
try {
    Invoke-Native 'tar' (@('-czf', $tgz, '-C', $root, '--exclude', '__pycache__') + $items)
    Write-Host ("package: {0:N1} MB" -f ((Get-Item -LiteralPath $tgz).Length / 1MB))
    Invoke-Native 'ssh' @($Server, "mkdir -p $dir && rm -rf $dir/src $dir/scripts $dir/web/dist")
    Invoke-Native 'scp' @('-q', $tgz, "${Server}:/tmp/playnext-deploy.tgz")
    if ($CopyEnv) { Invoke-Native 'scp' @('-q', (Join-Path $root '.env'), "${Server}:$dir/.env") }
    Invoke-Native 'ssh' @($Server, "tar -xzf /tmp/playnext-deploy.tgz -C $dir --no-same-owner && rm /tmp/playnext-deploy.tgz && tr -d '\r' < $dir/scripts/deploy/server.sh > /tmp/playnext-server.sh && bash /tmp/playnext-server.sh")
} finally {
    Remove-Item -LiteralPath $tgz -ErrorAction SilentlyContinue
}
