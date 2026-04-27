#!/usr/bin/env bash
# FNLeak launcher — runs the GUI.
# Usage:  ./run.sh           (GUI)
#         ./run.sh --cli     (terminal CLI, no GUI)

cd "$(dirname "$0")"

# Check Python 3.10+
PY=$(python3 -c "import sys; print(sys.version_info >= (3,10))" 2>/dev/null)
if [ "$PY" != "True" ]; then
  echo "ERROR: Python 3.10 or newer is required."
  echo "Download from https://www.python.org/downloads/"
  exit 1
fi

# Install/upgrade dependencies quietly
pip3 install -q -r requirements.txt

if [ "$1" == "--cli" ]; then
  python3 bot.py
else
  python3 gui.py
fi
