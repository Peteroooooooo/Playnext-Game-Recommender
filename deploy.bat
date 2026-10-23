@echo off
rem Double-click to push this PC's code, web app and data to the server (cubie) and restart the public service.
rem Extra options can be passed from a terminal, e.g.  deploy.bat -SkipData   (see scripts\deploy.ps1)
title Playnext deploy
where pwsh >nul 2>nul
if errorlevel 1 (
    echo PowerShell 7 ^(pwsh^) was not found. Install it from https://aka.ms/powershell
    pause
    exit /b 1
)
pwsh -NoLogo -NoProfile -File "%~dp0scripts\deploy.ps1" %*
if errorlevel 1 (
    echo.
    echo Deploy FAILED, see the messages above.
) else (
    echo.
    echo Deploy finished: the public site now runs this version.
)
pause
