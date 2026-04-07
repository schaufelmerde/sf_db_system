@echo off
call "%~dp0venv\Scripts\activate.bat"

echo Starting class_cam server...
start "class_cam" python "%~dp0class_cam.py"

echo Waiting for class_cam server to be ready...
:wait_loop
python -c "import socket; s=socket.create_connection(('localhost',5000),timeout=1); s.close()" 2>nul && goto :ready
timeout /t 1 /nobreak >nul
goto :wait_loop
:ready
echo Server is up!

echo Starting classifier...
python "%~dp0classifier.py"
pause
