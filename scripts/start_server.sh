#!/usr/bin/env bash
set -e

PROD_DIR="$HOME/.local/share/local-ai-brain-prod"

# If the directory doesn't exist, this might be the first run, let's gracefully fail
if [ ! -d "$PROD_DIR" ]; then
    echo "Production directory not found. Please run scripts/install_prod.sh first."
    exit 1
fi

cd "$PROD_DIR"

echo "Checking for updates..."
git fetch --tags
LATEST_TAG=$(git describe --tags $(git rev-list --tags --max-count=1) 2>/dev/null || echo "")

if [ -n "$LATEST_TAG" ]; then
    echo "Checking out latest tag: $LATEST_TAG"
    git checkout "$LATEST_TAG"
fi

echo "Syncing dependencies..."
export PATH="$HOME/.cargo/bin:/opt/homebrew/bin:$PATH"
UV_BIN=$(command -v uv || true)
if [ -z "$UV_BIN" ]; then
    echo "uv not found in PATH. Ensure uv is installed and available in $HOME/.cargo/bin or /opt/homebrew/bin."
    exit 1
fi
"$UV_BIN" sync --frozen

echo "Starting server on port 8000..."
PYTHONPATH=src "$UV_BIN" run uvicorn local_ai_brain.main:app --host 0.0.0.0 --port 8000
