#!/bin/bash
# Arby Runner Script
# Handles path setup, venv detection, and server launch

# Run source ../.venv/bin/activate to start the virtual environment
# Run ./arby start and verify the server starts.
# Run ./arby stop and verify the process is killed.
# Run ./arby restart and verify it cycles correctly.
# Run ./arby status to confirm it sees the process.
# Run ./arby check to run a live health check.
# Run ./arby logs to monitor the logs.

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
    echo "⚠️ Verification failed. Attempting to install missing dependencies..."
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    else
        pip install markdown flask python-dotenv schedule pydantic google-genai
    fi
    
    echo "🔄 Re-running verification..."
    python3 verify_app.py
    if [ $? -ne 0 ]; then
        echo "❌ Self-Check Failed! Syntax error or missing modules remain."
        exit 1
    fi
fi

# 4. Launch Server
python3 -m app.web.server
