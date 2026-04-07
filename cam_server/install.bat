@echo off
echo Removing old virtual environment...
if exist "%~dp0venv" rmdir /s /q "%~dp0venv"

echo Creating virtual environment...
echo Available Python versions:
py --list
py -3.10 -m venv "%~dp0venv"

echo Checking Python version...
"%~dp0venv\Scripts\python.exe" --version
"%~dp0venv\Scripts\python.exe" -c "import struct; print('Architecture:', '64-bit' if struct.calcsize('P')*8 == 64 else '32-bit')"

echo Activating virtual environment...
call "%~dp0venv\Scripts\activate.bat"

echo Installing requirements...
pip install -r "%~dp0requirements.txt"

echo Done. Dependencies installed.
pause
