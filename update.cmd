@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
if errorlevel 1 (
    echo.
    echo Update failed. Your existing files were kept.
)
pause
