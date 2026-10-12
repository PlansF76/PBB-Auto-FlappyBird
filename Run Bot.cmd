@echo off
cd /d "%~dp0"
python --version >nul 2>nul
if errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        py -3 "%~dp0auto_replay.py" %*
        if errorlevel 1 pause
        exit /b
    )
    echo Python was not found on PATH. Install Python 3.11 or newer, then run:
    echo     python -m pip install -r requirements.txt
    pause
    exit /b 1
)
python "%~dp0auto_replay.py" %*
if errorlevel 1 pause
