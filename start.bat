@echo off
title Snacky Studio - Universal Video Downloader (YouTube, Instagram, TikTok, Facebook)
cd /d "%~dp0"
echo Starting Snacky Studio Universal Video Downloader...
if not exist ".venv\Scripts\python.exe" (
    echo Please create the virtual environment and install requirements first.
    echo python -m venv .venv
    echo .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
".\.venv\Scripts\python.exe" run.py
pause
