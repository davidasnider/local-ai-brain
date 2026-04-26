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
    if command -v brew &> /dev/null; then
        brew install uv
    else
        echo "brew not found, attempting to install uv via standalone installer..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
    fi
fi

uv sync --frozen --no-dev

# Register and enable macOS launchd service
PLIST_PATH="$HOME/Library/LaunchAgents/com.localbrain.api.plist"
echo "Registering macOS LaunchAgent to $PLIST_PATH..."

if [ -z "$LOCAL_API_KEY" ]; then
    echo "Error: LOCAL_API_KEY environment variable is not set. It is required for the production service." >&2
    exit 1
fi

# Store the API key in a protected .env file instead of the plist
echo "LOCAL_API_KEY=$LOCAL_API_KEY" > "$PROD_DIR/.env"
chmod 600 "$PROD_DIR/.env"

# Register and enable macOS launchd service
PLIST_PATH="$HOME/Library/LaunchAgents/com.localbrain.api.plist"
echo "Registering macOS LaunchAgent to $PLIST_PATH..."

# Write the LaunchAgent plist without the LOCAL_API_KEY entry
perl -0pe 's/\n[ \t]*<key>LOCAL_API_KEY<\/key>[ \t]*\n[ \t]*<string>__REPLACE_WITH_LOCAL_API_KEY__<\/string>[ \t]*\n/\n/g' com.localbrain.api.plist > "$PLIST_PATH"

# Unload existing instance if present
launchctl unload "$PLIST_PATH" 2>/dev/null || true
# Load the fresh agent
launchctl load "$PLIST_PATH"

echo "Installation and persistent background registration complete."
