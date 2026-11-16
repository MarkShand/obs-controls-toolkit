@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-Windows.ps1" --uninstall %*
set "status=%errorlevel%"
if "%~1"=="" pause
exit /b %status%
