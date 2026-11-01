@echo off
rem Backs up the Biashara Check database, encryption key, callback secret, .env and trained model.
rem Double-click it, or schedule it with:  backup.bat --quiet
cd /d "%~dp0"
if /i "%~1"=="--quiet" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup.ps1" -Quiet
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup.ps1"
)
