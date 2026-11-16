#!/bin/bash
folder="$(cd "$(dirname "$0")" && pwd)" || exit 1
exec /bin/bash "$folder/Setup-Mac.command" --uninstall "$@"
