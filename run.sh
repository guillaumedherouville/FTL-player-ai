#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Start the Python agent — it binds the socket and waits for FTL to connect.
# Launch FTL from Steam AFTER this script prints "Waiting for FTL to connect".
echo "[agent] Starting..."
cd "$SCRIPT_DIR/agent"
"$SCRIPT_DIR/agent/.venv/bin/python3" -u agent.py
