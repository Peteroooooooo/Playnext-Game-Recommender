@echo off
rem Double-click to start Playnext: Docker Desktop, the playnext-db container, then the app on port 8000.
rem Close the window or press Ctrl+C to stop the app (the database container keeps running).
title Playnext
where pwsh >nul 2>nul
if errorlevel 1 (
    echo PowerShell 7 ^(pwsh^) was not found. Install it from https://aka.ms/powershell
    pause
    exit /b 1
)
pwsh -NoLogo -NoProfile -File "%~dp0scripts\serve.ps1"
if errorlevel 1 pause
