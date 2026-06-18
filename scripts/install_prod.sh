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

# Verify python3 is installed before any python3 calls
command -v python3 &>/dev/null || { echo "Error: python3 not found" >&2; exit 1; }

# Helper function to update LOCAL_API_KEY in a .env file
update_env_key() {
    local env_file="$1"
    local key="$2"
    python3 -c '
import sys, re
env_file = sys.argv[1]
key = sys.argv[2]
with open(env_file, "r") as f:
    content = f.read()
new_content = re.sub(
    r"^[ \t]*(export[ \t]+)?LOCAL_API_KEY[ \t]*=.*",
    lambda m: f"LOCAL_API_KEY=\"{key}\"",
    content,
    flags=re.MULTILINE
)
with open(env_file, "w") as f:
    f.write(new_content)
' "$env_file" "$key"
}

# Read only LOCAL_API_KEY from the .env file without executing arbitrary shell code
if [ -z "$LOCAL_API_KEY" ]; then
    if [ -f "$ENV_FILE" ]; then
        LOCAL_API_KEY="$(python3 -c '
import sys, re
with open(sys.argv[1]) as f:
    for line in f:
        m = re.match(r"^\s*(?:export\s+)?LOCAL_API_KEY\s*=\s*(.*)", line)
        if m:
            val = m.group(1).strip()
            if val.startswith("\""):
                q = re.match(r"^\"((?:[^\"\\]|\\.)*)\"(.*)", val)
                if q: val = q.group(1)
            elif val.startswith("\x27"):
                q = re.match(r"^\x27((?:[^\x27\\]|\\.)*)\x27(.*)", val)
                if q: val = q.group(1)
            else:
                val = re.sub(r"\s*#.*", "", val)
            print(val)
            break
' "$ENV_FILE")"
    fi
fi

PROD_DIR="$HOME/.local/share/local-ai-brain-prod"
REPO_URL="https://github.com/davidasnider/local-ai-brain.git"

echo "Installing Local AI Brain Production to $PROD_DIR"
mkdir -p "$(dirname "$PROD_DIR")"
if [ ! -d "$PROD_DIR" ]; then
    git clone "$REPO_URL" "$PROD_DIR"
fi

cd "$PROD_DIR"
git fetch --tags
TOP_TAG=$(git tag -l --sort=-v:refname | head -n 1 2>/dev/null || true)
if [ -n "$TOP_TAG" ]; then
    echo "Checking out latest tag: $TOP_TAG"
    git checkout --force "$TOP_TAG"
else
    echo "Warning: No git tags found or git command failed. Proceeding with default branch."
    # Ensure we are on the main branch before pulling, to avoid detached HEAD issues
    git checkout --force main
    git pull || echo "Warning: git pull failed, continuing anyway."
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
    if grep -E -q "^[[:space:]]*(export[[:space:]]+)?LOCAL_API_KEY=" "$PROD_DIR/.env"; then
        update_env_key "$PROD_DIR/.env" "$LOCAL_API_KEY"
        echo "Updated LOCAL_API_KEY in existing .env."
    else
        # Ensure trailing newline before appending
        if [ -s "$PROD_DIR/.env" ] && [ "$(tail -c1 "$PROD_DIR/.env" | wc -l)" -eq 0 ]; then
            echo >> "$PROD_DIR/.env"
        fi
        echo "LOCAL_API_KEY=\"$LOCAL_API_KEY\"" >> "$PROD_DIR/.env"
        echo "Appended LOCAL_API_KEY to existing .env."
    fi
else
    # Pre-create the file with secure permissions to prevent permission race condition
    touch "$PROD_DIR/.env"
    chmod 600 "$PROD_DIR/.env"

    if [ -f "$ENV_FILE" ]; then
        if [ "$ENV_FILE" -ef "$PROD_DIR/.env" ]; then
            update_env_key "$PROD_DIR/.env" "$LOCAL_API_KEY"
        else
            cp "$ENV_FILE" "$PROD_DIR/.env"
            chmod 600 "$PROD_DIR/.env"
            if grep -E -q "^[[:space:]]*(export[[:space:]]+)?LOCAL_API_KEY=" "$PROD_DIR/.env"; then
                update_env_key "$PROD_DIR/.env" "$LOCAL_API_KEY"
            else
                # Ensure trailing newline before appending
                if [ -s "$PROD_DIR/.env" ] && [ "$(tail -c1 "$PROD_DIR/.env" | wc -l)" -eq 0 ]; then
                    echo >> "$PROD_DIR/.env"
                fi
                echo "LOCAL_API_KEY=\"$LOCAL_API_KEY\"" >> "$PROD_DIR/.env"
                chmod 600 "$PROD_DIR/.env"
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

# Check if GUI session is available before registering the service
if launchctl print "gui/$(id -u)" &>/dev/null; then
    # Unload existing instance if present
    launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
    # Load the fresh agent
    launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
else
    echo "Warning: GUI session not available for user $(id -u). LaunchAgent was not registered."
fi


echo "Installation and persistent background registration complete."
