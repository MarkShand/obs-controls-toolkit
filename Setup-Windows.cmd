@echo off
setlocal
cd /d "%~dp0"
python -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo Install Python 3.10 or newer with Tcl/Tk and add Python to PATH, then try again.
  goto done
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if not exist ".venv\Scripts\python.exe" goto done
".venv\Scripts\python.exe" -c "import obsws_python, send2trash, av" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r video-rundown\requirements.txt
  if errorlevel 1 goto done
)
echo First run: see README.md for the OBS scripts and dock URLs.
echo Keep this window open while using Video Rundown.
".venv\Scripts\python.exe" video-rundown\video_rundown.py
:done
pause
