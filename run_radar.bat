@echo off
title Lobby News Radar
rem Double-click to start the radar. Leave this window open. Close it to stop.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python from python.org and tick "Add python.exe to PATH".
  echo See README.txt step 1.
  pause
  exit /b 1
)
:loop
echo.
echo [%date% %time%] Starting Lobby News Radar...
python radar.py --loop
if %errorlevel%==3 (
  echo.
  echo The radar is already running in another window. This window will close.
  pause
  exit /b 0
)
if %errorlevel%==2 (
  echo.
  echo A settings file has a mistake - see the message above. Fix it, then start again.
  pause
  exit /b 2
)
echo.
echo The radar stopped (code %errorlevel%). Restarting in 30 seconds... Close this window to stop it.
timeout /t 30 /nobreak >nul
goto loop
