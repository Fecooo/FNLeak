@echo off
:: FNLeak launcher for Windows- NOT mac
:: Double-click this file, or run from Command Prompt / PowerShell.
:: Usage:
::   run.bat          -> launches GUI
::   run.bat --cli    -> launches terminal CLI

cd /d "%~dp0"

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Download Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Check Python version is 3.10+
python -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.10 or newer is required.
    echo Download from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Install / upgrade dependencies silently
echo Installing dependencies...
pip install -q -r requirements.txt

if "%1"=="--cli" (
    python bot.py
) else (
    python gui.py
)

pause
