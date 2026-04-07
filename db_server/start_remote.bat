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
set DB=%ROOT%db_server
set CAM=%ROOT%..\cam_server
set VENV=%ROOT%dbvenv\Scripts
set DASHBOARD=%ROOT%sf-dashboard

set /p CAM_HOST=Camera server IP (leave blank for localhost):
if "%CAM_HOST%"=="" set CAM_HOST=localhost
echo Using camera server at %CAM_HOST%:5000
echo.

echo [1/4] Starting API server (remote DB mode)...
start "SF API" cmd /k "cd /d %ROOT% && %VENV%\uvicorn.exe main_remote:app --reload --host 0.0.0.0 --port 8000"

echo [2/4] Starting PLC order controller...
start "SF PLC Controller" cmd /k "cd /d %ROOT% && %VENV%\python.exe plc_order_controller.py"

echo [3/4] Starting camera server...
start "SF CAM" cmd /k "cd /d %CAM% && call venv\Scripts\activate.bat && python class_cam.py"

echo [4/4] Starting dashboard...
start "SF Dashboard" cmd /k "cd /d %DASHBOARD% && set CAM_HOST=%CAM_HOST% && npm run dev"

echo      Waiting for API to be ready...
:wait_api
curl -s http://localhost:8000/api/init-data >nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 2 /nobreak >nul
    goto wait_api
)
start "" http://localhost:5173/

echo.
echo All services launched.
echo   API       ^> http://localhost:8000
echo   Dashboard ^> http://localhost:5173
echo.
pause
