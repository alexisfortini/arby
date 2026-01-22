#!/bin/bash
# Arby Runner Script
# Handles path setup, venv detection, and server launch

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
export PYTHONPATH="$DIR"

# 1. Detect and activate virtual environment if present
if [ -f "$DIR/.venv/bin/activate" ]; then
    source "$DIR/.venv/bin/activate"
elif [ -f "$DIR/venv/bin/activate" ]; then
    source "$DIR/venv/bin/activate"
fi

# 2. Check if .env exists
if [ ! -f "$DIR/.env" ]; then
    echo "ERROR: .env file not found. Please create one with your API keys!"
    exit 1
fi

echo "Starting Arby Web Server..."

# 3. Run Self-Check
python3 verify_app.py
if [ $? -ne 0 ]; then
    echo "❌ Self-Check Failed! Syntax error in code."
    exit 1
fi

# 4. Launch Server
python3 -m app.web.server
