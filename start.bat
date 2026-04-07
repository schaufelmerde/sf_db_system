@echo off
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set ROOT=%~dp0
set DB=%ROOT%db_server
set CAM=%ROOT%cam_server
set DB_VENV=%DB%\dbvenv\Scripts
set DASHBOARD=%DB%\sf-dashboard

echo ============================================================
echo  SF Server - Starting All Services
echo ============================================================
echo.

echo [DB] Starting MySQL service...
net start MySQL81 >nul 2>&1
:wait_mysql
sc query MySQL81 | find "RUNNING" >nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 2 /nobreak >nul
    goto wait_mysql
)
echo [DB] MySQL81 is running.

echo Launching service windows...

wt --maximized ^
    new-tab --title "SF API" cmd /k "cd /d "%DB%" && "%DB_VENV%\uvicorn.exe" main:app --reload --host 0.0.0.0 --port 8000" ^
    ; split-pane --vertical --title "SF PLC Controller" cmd /k "cd /d "%DB%" && "%DB_VENV%\python.exe" plc_order_controller.py" ^
    ; move-focus left ^
    ; split-pane --horizontal --size 0.3 --title "SF CAM" cmd /k "cd /d "%CAM%" && call venv\Scripts\activate.bat && python class_cam.py" ^
    ; split-pane --horizontal --size 0.5 --title "SF Dashboard" cmd /k "cd /d "%DASHBOARD%" && npm run dev"

echo.
echo Waiting for API to be ready...
:wait_api
curl -s http://localhost:8000/api/init-data >nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 2 /nobreak >nul
    goto wait_api
)
start "" http://localhost:5173/

echo.
echo ============================================================
echo  All services launched.
echo   API        - http://localhost:8000
echo   Dashboard  - http://localhost:5173
echo   CAM server - localhost:5000
echo ============================================================
echo.
pause
