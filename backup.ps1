# Biashara Check backup: database dump, encryption key, callback secret, .env and the trained model.
# Run with backup.bat. Saves to backups\YYYY-MM-DD_HHMM and keeps the newest 14 backups.
param([switch]$Quiet)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# database settings from DATABASE_URL in .env (XAMPP default if missing)
$url = "mysql+pymysql://root:@localhost:3306/sme_risk_db"
if (Test-Path .env) {
    $line = Get-Content .env | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
    if ($line) { $url = ($line -split '=', 2)[1].Trim() }
}
if ($url -notmatch '^mysql[^:]*://(?<user>[^:@/]*)(:(?<pass>[^@]*))?@(?<host>[^:/]+)(:(?<port>\d+))?/(?<db>[^?]+)') {
    Write-Host "DATABASE_URL in .env isn't a MySQL address; only the key files will be copied." -ForegroundColor Yellow
    $db = $null
} else {
    $user = $Matches.user; $pass = [uri]::UnescapeDataString("$($Matches.pass)")
    $dbHost = $Matches.host; $port = if ($Matches.port) { $Matches.port } else { "3306" }; $db = $Matches.db
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$dest = Join-Path (Join-Path $PSScriptRoot "backups") $stamp
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$ok = $true

if ($db) {
    $dump = @("C:\xampp\mysql\bin\mysqldump.exe", (Get-Command mysqldump -ErrorAction SilentlyContinue).Source) |
            Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $dump) {
        Write-Host "mysqldump not found (looked in C:\xampp\mysql\bin). Database NOT backed up." -ForegroundColor Red
        $ok = $false
    } else {
        $dumpArgs = @("--user=$user", "--host=$dbHost", "--port=$port", "--single-transaction", "--routines",
                  "--default-character-set=utf8mb4", "--result-file=$dest\$db.sql", $db)
        if ($pass) { $dumpArgs = @("--password=$pass") + $dumpArgs }
        $ErrorActionPreference = "Continue"   # mysqldump warnings on stderr shouldn't stop the script
        & $dump @dumpArgs
        $ErrorActionPreference = "Stop"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "mysqldump failed. Is MySQL running in XAMPP?" -ForegroundColor Red
            $ok = $false
        } else {
            Write-Host "Database $db saved."
        }
    }
}

foreach ($f in @("instance\contact.key", "instance\mpesa_callback.secret", ".env",
                 "ml\artifacts\model.joblib", "ml\artifacts\model_meta.json")) {
    if (Test-Path $f) {
        $to = Join-Path $dest $f
        New-Item -ItemType Directory -Force -Path (Split-Path $to) | Out-Null
        Copy-Item $f $to
        Write-Host "Copied $f"
    }
}
if (-not (Test-Path "instance\contact.key")) {
    Write-Host "Note: instance\contact.key not found. If CONTACT_KEY is set in .env, it is inside the copied .env." -ForegroundColor Yellow
}

# keep the newest 14
Get-ChildItem backups -Directory | Sort-Object Name -Descending | Select-Object -Skip 14 |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force }

if ($ok) { Write-Host "`nBackup saved in $dest" -ForegroundColor Green }
else { Write-Host "`nBackup in $dest is INCOMPLETE (see above)." -ForegroundColor Red }
Write-Host "Copy the backups folder to a flash disk or Google Drive now and then."
if (-not $Quiet) { Read-Host "Press Enter to close" | Out-Null }
if (-not $ok) { exit 1 }
