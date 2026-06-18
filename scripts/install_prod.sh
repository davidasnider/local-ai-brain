#!/usr/bin/env bash
set -e

# Get the directory of the script and repo root
ORIGINAL_PWD="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
case "$ENV_FILE" in
    /*) ;;
    *) ENV_FILE="$ORIGINAL_PWD/$ENV_FILE" ;;
esac

# Read only LOCAL_API_KEY from the .env file without executing arbitrary shell code
if [ -z "$LOCAL_API_KEY" ]; then
    if [ -f "$ENV_FILE" ]; then
        LOCAL_API_KEY="$(
            awk '
                /^[[:space:]]*(export[[:space:]]+)?LOCAL_API_KEY[[:space:]]*=/ {
                    value = $0
                    sub(/^[[:space:]]*(export[[:space:]]+)?LOCAL_API_KEY[[:space:]]*=[[:space:]]*/, "", value)
                    print value
                    exit
                }
            ' "$ENV_FILE"
        )"

        case "$LOCAL_API_KEY" in
            \"*\")
                LOCAL_API_KEY="${LOCAL_API_KEY#\"}"
                LOCAL_API_KEY="${LOCAL_API_KEY%\"}"
                ;;
            \'*\')
                LOCAL_API_KEY="${LOCAL_API_KEY#\'}"
                LOCAL_API_KEY="${LOCAL_API_KEY%\'}"
                ;;
        esac
    fi
fi

PROD_DIR="$HOME/.local/share/local-ai-brain-prod"
REPO_URL="https://github.com/davidasnider/local-ai-brain.git"

echo "Installing Local AI Brain Production to $PROD_DIR"
if [ ! -d "$PROD_DIR" ]; then
    git clone "$REPO_URL" "$PROD_DIR"
fi

cd "$PROD_DIR"
git fetch --tags
TAG_COMMIT=$(git rev-list --tags --max-count=1 2>/dev/null || true)
if [ -n "$TAG_COMMIT" ]; then
    LATEST_TAG=$(git describe --tags "$TAG_COMMIT" 2>/dev/null || echo "")
    if [ -z "$LATEST_TAG" ]; then
        echo "Warning: Tag resolution fell back. Proceeding with default branch."
    fi
else
    echo "Warning: No git tags found or git command failed. Proceeding with default branch."
    LATEST_TAG=""
fi

if [ -n "$LATEST_TAG" ]; then
    echo "Checking out latest tag: $LATEST_TAG"
    git checkout "$LATEST_TAG"
else
    # Ensure we are on the main branch before pulling, to avoid detached HEAD issues
    git checkout main
    git pull
fi

# Install uv if not present
if ! command -v uv &> /dev/null; then
    if command -v brew &> /dev/null; then
        brew install uv
    else
        echo "brew not found, attempting to install uv via standalone installer..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
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

# Copy the .env file or create one if it doesn't exist
if [ -f "$PROD_DIR/.env" ]; then
    echo "Warning: Production .env already exists at $PROD_DIR/.env. Skipping copy."
else
    # Pre-create the file with secure permissions to prevent permission race condition
    touch "$PROD_DIR/.env"
    chmod 600 "$PROD_DIR/.env"

    if [ -f "$ENV_FILE" ]; then
        if [ "$ENV_FILE" -ef "$PROD_DIR/.env" ]; then
            echo ".env already exists at destination; skipping copy."
        else
            cp "$ENV_FILE" "$PROD_DIR/.env"
            if ! grep -q "LOCAL_API_KEY=" "$PROD_DIR/.env"; then
                echo "LOCAL_API_KEY=\"$LOCAL_API_KEY\"" >> "$PROD_DIR/.env"
            fi
        fi
    else
        echo "LOCAL_API_KEY=\"$LOCAL_API_KEY\"" > "$PROD_DIR/.env"
    fi
fi
chmod 600 "$PROD_DIR/.env"

# Write the LaunchAgent plist without the LOCAL_API_KEY entry
mkdir -p "$HOME/Library/LaunchAgents"
cp com.localbrain.api.plist "$PLIST_PATH"
plutil -remove EnvironmentVariables.LOCAL_API_KEY "$PLIST_PATH" 2>/dev/null || true

# Unload existing instance if present
launchctl unload "$PLIST_PATH" 2>/dev/null || true
# Load the fresh agent
launchctl load "$PLIST_PATH"

echo "Installation and persistent background registration complete."
