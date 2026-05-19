#!/bin/bash
# NSE2 Automation - Git Push Script
# Usage: bash git_push.sh "commit message"

set -e

cd "$(dirname "$0")"

COMMIT_MSG="${1:-Update NSE Scanner}"

echo "========================================="
echo "  NSE2 Automation - Git Push"
echo "========================================="

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
    echo ""
    echo "Enter your GitHub repo URL (e.g., https://github.com/username/nse2-scanner.git):"
    read -r REPO_URL
    git remote add origin "$REPO_URL"
    echo "Remote added: $REPO_URL"
fi

# Show status
echo ""
echo "Current status:"
git status --short

# Stage all files
echo ""
echo "Staging files..."
git add -A

# Show what will be committed
echo ""
echo "Files to commit:"
git diff --cached --stat

# Commit
echo ""
echo "Committing: $COMMIT_MSG"
git commit -m "$COMMIT_MSG

🤖 Generated with OpenClaude"

# Push
echo ""
echo "Pushing to remote..."
BRANCH=$(git branch --show-current 2>/dev/null || echo "main")
git push -u origin "$BRANCH"

echo ""
echo "========================================="
echo "  Push complete!"
echo "========================================="
echo ""
echo "To deploy on Streamlit Cloud:"
echo "  1. Go to https://share.streamlit.io/"
echo "  2. Deploy from: your-repo/app.py"
echo "  3. Set secrets in Streamlit Cloud dashboard"
echo ""
