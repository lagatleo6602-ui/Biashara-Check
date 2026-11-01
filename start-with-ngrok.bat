@echo off
rem Starts ngrok (so Safaricom can send M-Pesa results to this laptop) and then the app.
rem Put your free ngrok address in .env as NGROK_URL=https://your-name.ngrok-free.dev
cd /d "%~dp0"

where ngrok >nul 2>nul
if errorlevel 1 (
  echo ngrok is not installed or not on PATH.
  echo Install it with:  winget install ngrok.ngrok
  echo then run:         ngrok config add-authtoken YOUR_TOKEN
  pause
  exit /b 1
)

set "NGROK_URL="
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /B /C:"NGROK_URL=" .env 2^>nul`) do set "NGROK_URL=%%b"

if defined NGROK_URL (
  echo Starting ngrok on %NGROK_URL% ...
  start "ngrok" ngrok http 127.0.0.1:8000 --url %NGROK_URL%
) else (
  echo Starting ngrok with a random address. Add NGROK_URL to .env to keep the same address.
  start "ngrok" ngrok http 127.0.0.1:8000
)

echo Starting Biashara Check on http://127.0.0.1:8000 ...
venv\Scripts\python -m uvicorn app.main:app --reload
