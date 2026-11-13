#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "Install Python 3 before continuing."
  exit 1
fi
swiftc -O source/tracking-toast.swift -o tracking-runtime/tracking-toast
echo "In OBS, open Tools > Scripts and add:"
echo "$PWD/outputs/obs-hotkey-toggle.lua"
echo "Under Docks > Custom Browser Docks, add OBS Controls at http://127.0.0.1:46642/"
open "$PWD/outputs"
