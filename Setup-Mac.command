#!/bin/bash
set -u
folder="$(cd "$(dirname "$0")" && pwd)" || exit 1
for candidate in \
    "$folder/.venv/bin/python" \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 \
    "$(command -v python3 || true)"; do
  # /usr/bin/python3 can start an Xcode install prompt on an unconfigured Mac.
  if [[ "$candidate" == /usr/bin/python3 ]] && ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
    continue
  fi
  if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    exec "$candidate" "$folder/setup_toolkit.py" "$@"
  fi
done
echo "Install Python 3.10 or newer from https://www.python.org/downloads/macos/"
echo "Then run this command again."
exit 1
