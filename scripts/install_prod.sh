#!/usr/bin/env bash
set -e

PROD_DIR="$HOME/.local/share/local-ai-brain-prod"
REPO_URL="https://github.com/davidasnider/local-ai-brain.git"

echo "Installing Local AI Brain Production to $PROD_DIR"
if [ ! -d "$PROD_DIR" ]; then
    git clone "$REPO_URL" "$PROD_DIR"
fi

cd "$PROD_DIR"
git fetch --tags
LATEST_TAG=$(git describe --tags $(git rev-list --tags --max-count=1) 2>/dev/null || echo "")

if [ -n "$LATEST_TAG" ]; then
    echo "Checking out latest tag: $LATEST_TAG"
    git checkout "$LATEST_TAG"
fi

# Install uv if not present
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

export PATH="$HOME/.cargo/bin:$PATH"
uv sync

# Register and enable macOS launchd service
PLIST_PATH="$HOME/Library/LaunchAgents/com.localbrain.api.plist"
echo "Registering macOS LaunchAgent to $PLIST_PATH..."
cp com.localbrain.api.plist "$PLIST_PATH"

# Unload existing instance if present
launchctl unload "$PLIST_PATH" 2>/dev/null || true
# Load the fresh agent
launchctl load "$PLIST_PATH"

echo "Installation and persistent background registration complete."
