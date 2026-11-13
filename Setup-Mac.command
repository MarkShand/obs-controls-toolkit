#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "Install Python 3.10 or newer and run setup again."
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else "Python 3.10 or newer is required.")'
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if [ ! -x tracking-runtime/tracking-toast ] || [ source/tracking-toast.swift -nt tracking-runtime/tracking-toast ]; then
  if ! xcode-select -p >/dev/null 2>&1; then
    echo "Install the Xcode Command Line Tools to build the optional tracking toast."
  else
    swiftc -O source/tracking-toast.swift -o tracking-runtime/tracking-toast
  fi
fi
if ! .venv/bin/python -c 'import obsws_python, send2trash, av' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r video-rundown/requirements.txt
fi
echo "First run: see README.md for the OBS scripts and dock URLs."
echo "Keep this window open while using Video Rundown."
exec .venv/bin/python video-rundown/video_rundown.py
