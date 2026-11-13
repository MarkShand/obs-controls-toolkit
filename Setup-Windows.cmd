@echo off
cd /d "%~dp0"
python -c "import tkinter, http.server"
if errorlevel 1 (
  echo Install Python 3 with Tcl/Tk and add Python to PATH, then try again.
  pause
  exit /b 1
)
echo In OBS, open Tools ^> Scripts and add:
echo %CD%\outputs\obs-hotkey-toggle.lua
echo Under Docks ^> Custom Browser Docks, add OBS Controls at http://127.0.0.1:46642/
explorer "%CD%\outputs"
pause
