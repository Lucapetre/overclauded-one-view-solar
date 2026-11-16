@echo off
setlocal
rem SolarLens local demo: double-click to start. Close this window to stop the server.
rem Everyone gets the same demo: the database is generated from fixed seeds and fixtures.
cd /d "%~dp0"

set "PORT=8020"
for %%I in ("%~dp0..") do set "WS=%%~fI\ovs-demo"
set "TEMP=%WS%-tmp"
set "TMP=%WS%-tmp"
if not exist "%TEMP%" mkdir "%TEMP%"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo Creating the Python environment ^(first run only^)...
  py -3.12 -m venv .venv || python -m venv .venv || (echo [!] Install Python 3.12 and try again. & pause & exit /b 1)
  "%PY%" -m pip install -e ".[dev]" || (pause & exit /b 1)
)

"%PY%" -m scripts.setup_demo --workspace "%WS%" --status
if errorlevel 3 (
  echo.
  echo [!] "%WS%" is from an older version or an unfinished setup.
  choice /m "Delete it and rebuild the demo database now"
  if errorlevel 2 exit /b 1
  rmdir /s /q "%WS%"
  goto build
)
if errorlevel 2 goto build
goto frontend

:build
echo Building the demo database in "%WS%" ^(a few minutes, one time^)...
"%PY%" -m scripts.setup_demo --workspace "%WS%" --skip-frontend || (pause & exit /b 1)

:frontend
if not exist "frontend\node_modules" (
  echo Installing frontend packages ^(first run only^)...
  call npm --prefix frontend ci || (pause & exit /b 1)
)
echo Building the frontend...
call npm --prefix frontend run build >nul || (pause & exit /b 1)

set "SOLAR_DATABASE=%WS%\api.sqlite3"
set "SOLAR_MEDIA_DIR=%WS%\media"
set "SOLAR_OFFER_WORKER=false"
set "SOLAR_DEMO_LOGIN=true"
set "SOLAR_DEMO_LAN=true"

echo.
echo  SolarLens is starting...
echo    Laptop: http://127.0.0.1:%PORT%/demo/
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp -ErrorAction SilentlyContinue | Select-Object -First 1).IPAddress"`) do echo    Phone ^(same Wi-Fi^): http://%%A:%PORT%/demo/
echo    Password for every account: SolarDemo2026!
echo    If Windows Firewall asks, click Allow. Close this window to stop.
echo.

if not defined SOLAR_NO_BROWSER start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:%PORT%/demo/"
"%PY%" -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT%
pause
