#!/bin/bash

# Default commit message if none provided
MSG=${1:-"Update"}

echo "🚀 Starting Release Process..."

# 1. Stage all changes
echo "📦 Staging files..."
git add .

# 2. Check status
STATUS=$(git status --porcelain)

if [ -z "$STATUS" ]; then
    echo "✨ Working tree clean. Nothing to commit."
    exit 0
fi

# 3. Generate Changelog from diff stat
echo "📝 Generating changelog..."
STATS=$(git diff --cached --stat)
FULL_MSG="$MSG

$STATS"

# 4. Commit
echo "💾 Committing..."
git commit -m "$FULL_MSG"

# 5. Push
echo "⬆️ Pushing to origin..."
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin $CURRENT_BRANCH

echo "✅ Release Pushed Successfully!"
