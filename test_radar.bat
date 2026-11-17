@echo off
title Lobby News Radar - test
rem Double-click to test: sends a test Telegram message + sample card, then does one check.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
echo === Step 1: test message and sample card ===
python radar.py --test
echo.
echo === Step 2: one check of all sources ===
python radar.py --once
echo.
echo Done. Read the table above: every source should say OK.
pause
