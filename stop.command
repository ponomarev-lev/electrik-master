#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python3 >/dev/null 2>&1; then
  python3 launcher.py stop
elif command -v python >/dev/null 2>&1; then
  python launcher.py stop
else
  echo "Python 3 was not found."
  echo "Install Python 3 and run this file again."
fi

echo ""
echo "Press Enter to close this window."
read -r
