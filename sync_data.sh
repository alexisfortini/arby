#!/bin/bash

# Arby Data Sync Script
# Helps synchronize the local 'state' directory with the GCP Cloud Storage bucket.

PROJECT_ID="gen-lang-client-0397594216"
BUCKET="gs://arby-state-$PROJECT_ID"
LOCAL_DIR="./state"

# Ensure local state directory exists
mkdir -p "$LOCAL_DIR"

usage() {
    echo "Usage: ./sync_data.sh [push|pull]"
    echo "  push: Upload local data to the Cloud (CAUTION: Overwrites cloud data)"
    echo "  pull: Download cloud data to Local (CAUTION: Overwrites local data)"
    exit 1
}

if [ -z "$1" ]; then
    usage
fi

case "$1" in
    push)
        echo "📤 Pushing local state to Google Cloud..."
        gsutil -m rsync -r "$LOCAL_DIR" "$BUCKET"
        echo "✅ Push complete."
        ;;
    pull)
        echo "📥 Pulling cloud state to Local..."
        gsutil -m rsync -r "$BUCKET" "$LOCAL_DIR"
        echo "✅ Pull complete."
        ;;
    *)
        usage
        ;;
esac
