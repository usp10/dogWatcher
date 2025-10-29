@echo off

REM Simple BTC/PAXG Monitor Launcher
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

cls

echo ===================================================
echo          BTC/PAXG RATIO MONITOR LAUNCHER          
echo ===================================================
echo.
echo Functions:
echo 1. Calculate BTC/PAXG ratio every 5 minutes
echo 2. Push to DingTalk
echo 3. Alert when ratio below 26

echo.

REM Check Python installation
echo Checking Python installation...
python --version
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Please install Python first.
    echo Download: https://www.python.org/
    pause
    exit /b 1
)

REM Check and install requests
echo.
echo Checking required packages...
python -c "import requests" 2>nul
if %errorlevel% neq 0 (
    echo Installing requests package...
    pip install requests
    if %errorlevel% neq 0 (
        echo ERROR: Failed to install requests. Please run 'pip install requests' manually.
        pause
        exit /b 1
    )
)

REM Create logs folder if not exists
if not exist "logs" (
    mkdir logs
)

REM Important notice
echo.
echo IMPORTANT NOTICE:
echo Please make sure you have set the correct DingTalk robot token in btc_paxg_ratio_monitor.py
echo Look for this line and replace with your token:
echo self.dingtalk_token = "your_dingtalk_robot_token"

echo.
echo Starting monitor automatically...


REM Run the Python script
python btc_paxg_ratio_monitor.py

REM Check result
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Monitor stopped with errors. Check logs for details.
    pause
    exit /b 1
)

pause