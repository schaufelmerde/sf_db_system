@echo off
setlocal enabledelayedexpansion

set ROOT=%~dp0
set VENV=%ROOT%dbvenv\Scripts
set DASHBOARD=%ROOT%sf-dashboard

echo [1/4] Creating virtual environment...
if exist "%ROOT%dbvenv" (
    echo      Stopping any running processes using dbvenv...
    taskkill /F /FI "WINDOWTITLE eq SF API" >nul 2>&1
    taskkill /F /FI "WINDOWTITLE eq SF PLC Controller" >nul 2>&1
    taskkill /F /FI "WINDOWTITLE eq SF Dashboard" >nul 2>&1
    taskkill /F /IM uvicorn.exe >nul 2>&1
    taskkill /F /IM python.exe >nul 2>&1
    timeout /t 3 /nobreak >nul
)

if exist "%ROOT%dbvenv" (
    echo      Renaming old dbvenv for cleanup...
    if exist "%ROOT%dbvenv_old" rmdir /s /q "%ROOT%dbvenv_old" >nul 2>&1
    rename "%ROOT%dbvenv" dbvenv_old
    if exist "%ROOT%dbvenv" (
        echo      ERROR: Could not rename dbvenv. Close VS Code or any terminal using it and re-run.
        pause
        exit /b 1
    )
    echo      Old venv staged for background cleanup.
    start "" /b cmd /c "timeout /t 5 /nobreak >nul && rmdir /s /q ""%ROOT%dbvenv_old"" >nul 2>&1"
)
python -m venv "%ROOT%dbvenv"
if %errorlevel% neq 0 (
    echo      ERROR: Failed to create venv. Is Python installed and on PATH?
    pause
    exit /b 1
)
echo      dbvenv created.

echo [2/4] Starting MySQL service...
net start MySQL81 >nul 2>&1

:wait_mysql
sc query MySQL81 | find "RUNNING" >nul 2>&1
if %errorlevel% neq 0 (
    echo      Waiting for MySQL81 to be ready...
    timeout /t 2 /nobreak >nul
    goto wait_mysql
)
echo      MySQL81 is running.

echo [3/4] Installing Python dependencies...
%VENV%\pip.exe install -r "%ROOT%requirements.txt"
if %errorlevel% neq 0 (
    echo      ERROR: pip install failed.
    pause
    exit /b 1
)
echo      Dependencies installed.

echo [4/5] Installing Node packages for sf-dashboard...
cd /d "%DASHBOARD%"
npm install
if %errorlevel% neq 0 (
    echo      ERROR: npm install failed. Is Node.js installed and on PATH?
    pause
    exit /b 1
)
echo      Node packages installed.
cd /d "%ROOT%"

echo [5/5] Running database setup...
%VENV%\python.exe "%ROOT%db_setup.py"
if %errorlevel% neq 0 (
    echo      ERROR: db_setup.py failed.
    pause
    exit /b 1
)

echo.
echo Installation complete.
echo Run start.bat to launch the application.
echo.
pause
