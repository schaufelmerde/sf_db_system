@echo off
setlocal

:: Re-launch as administrator if not already elevated
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set ROOT=%~dp0
set VENV=%ROOT%dbvenv\Scripts
set DASHBOARD=%ROOT%sf-dashboard

echo [1/3] Starting API server (remote DB mode)...
start "SF API" cmd /k "cd /d %ROOT% && %VENV%\uvicorn.exe main_remote:app --reload --host 0.0.0.0 --port 8000"

echo [2/3] Starting PLC order controller...
start "SF PLC Controller" cmd /k "cd /d %ROOT% && %VENV%\python.exe plc_order_controller.py"

echo [3/3] Starting dashboard...
start "SF Dashboard" cmd /k "cd /d %DASHBOARD% && npm run dev"

echo      Opening browser...
timeout /t 3 /nobreak >nul
start "" http://localhost:5173/

echo.
echo All services launched.
echo   API       ^> http://localhost:8000
echo   Dashboard ^> http://localhost:5173
echo.
pause
