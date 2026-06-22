#!/usr/bin/env bash
set -e

# Get the directory of the script and repo root
ORIGINAL_PWD="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

# Expand ~ to $HOME in ENV_FILE paths
# For named user paths, we expand using shell eval
if [[ "$ENV_FILE" == ~* ]]; then
    ENV_FILE=$(eval echo "$ENV_FILE")
fi

case "$ENV_FILE" in
    /*) ;;
    *) ENV_FILE="$ORIGINAL_PWD/$ENV_FILE" ;;
esac

# Helper function to update LOCAL_API_KEY in a .env file
update_env_key() {
    local env_file="$1"
    if [ -z "$INSTALL_HELPERS" ]; then
        INSTALL_HELPERS="$SCRIPT_DIR/install_helpers.py"
    fi
    LOCAL_API_KEY_VALUE="$LOCAL_API_KEY" ${PYTHON:-python3} "$INSTALL_HELPERS" update_env_key "$env_file"
}

# Helper to write LOCAL_API_KEY to .env with proper escaping of backslashes and quotes
_write_env_key() {
    local _ekey="${LOCAL_API_KEY//\\/\\\\}"
    _ekey="${_ekey//\"/\\\"}"
    _ekey="${_ekey//\$/\\\$}"
    _ekey="${_ekey//\`/\\\`}"
    printf 'LOCAL_API_KEY="%s"\n' "$_ekey"
}

# Upsert LOCAL_API_KEY in a .env file: update if present, append if missing
_upsert_api_key() {
    local env_file="$1"
    if grep -E -q "^[[:space:]]*(export[[:space:]]+)?LOCAL_API_KEY=" "$env_file"; then
        update_env_key "$env_file"
    else
        # Ensure trailing newline before appending
        if [ -s "$env_file" ] && [ "$(tail -c1 "$env_file" | wc -l)" -eq 0 ]; then
            echo >> "$env_file"
        fi
        _write_env_key >> "$env_file"
    fi
}


# Execution guard: only run main body if executed directly (not sourced)
# This allows tests to source the script and access helper functions directly.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    umask 077

    if [ "$EUID" -eq 0 ]; then
        echo "Error: This installer should not be run as root." >&2
        exit 1
    fi
    # Copy install_helpers.py to a temp path so it survives git checkout (which may
    # delete or overwrite the file when switching between tag versions in $PROD_DIR)
    # Uses mktemp -d to avoid the macOS mktemp template-suffix issue:
    # BSD mktemp only randomizes XXXXXX when it appears at the very end of the template,
    # so appending .py after the subshell would leak the original file created by mktemp.
    # The temp dir and helpers are only needed during direct execution, not when sourced.
    INSTALL_HELPERS_DIR=$(mktemp -d /tmp/install_helpers.XXXXXXXXXX)
    # Register cleanup to prevent temp file leaks
    # Use a more robust way to retrieve EXIT trap commands by using a temporary file
    # to store the existing trap command, avoiding quoting/escaping issues with 'eval'.
    trap_file=$(mktemp /tmp/trap_XXXXXX)
    trap -p EXIT > "$trap_file"
    if [ -s "$trap_file" ]; then
        # The output of trap -p EXIT is: trap -- 'command' EXIT
        # We need to extract the command between the single quotes.
        existing_cmd=$(sed -n "s/^trap -- '\(.*\)' EXIT$/\1/p" "$trap_file")
        # Ensure we properly escape the existing command for the subshell to run it
        # Actually, since it's already a bash command string, we can just use it
        # in a function.
        run_exit_trap() {
            eval "$existing_cmd"
            rm -rf "$INSTALL_HELPERS_DIR"
            rm -f "$trap_file"
        }
        trap run_exit_trap EXIT
    else
        trap 'rm -rf "$INSTALL_HELPERS_DIR"; rm -f "$trap_file"' EXIT
    fi
    rm -f "$trap_file"
    INSTALL_HELPERS="$INSTALL_HELPERS_DIR/install_helpers.py"
    cp "$SCRIPT_DIR/install_helpers.py" "$INSTALL_HELPERS"

    # Verify python3 is installed before any python3 calls
    command -v python3 &>/dev/null || { echo "Error: python3 not found" >&2; exit 1; }

    # Read only LOCAL_API_KEY from the .env file without executing arbitrary shell code
    if [ -z "$LOCAL_API_KEY" ]; then
        if [ -f "$ENV_FILE" ]; then
            LOCAL_API_KEY="$(${PYTHON:-python3} "$INSTALL_HELPERS" read_env_key "$ENV_FILE")"
        fi
    fi

    PROD_DIR="$HOME/.local/share/local-ai-brain-prod"
    REPO_URL="https://github.com/davidasnider/local-ai-brain.git"

    echo "Installing Local AI Brain Production to $PROD_DIR"
    mkdir -p "$(dirname "$PROD_DIR")"
    # If PROD_DIR exists as a regular file, error out
    if [ -f "$PROD_DIR" ]; then
        echo "Error: $PROD_DIR exists as a regular file. Please remove it: rm -f '$PROD_DIR'" >&2
        exit 1
    fi
    # If PROD_DIR exists but is not a git repository, error out to prevent data loss
    if [ -d "$PROD_DIR" ] && [ ! -d "$PROD_DIR/.git" ]; then
        echo "Error: $PROD_DIR exists but is not a git repository." >&2
        echo "Please remove it manually and re-run the installer: rm -rf '$PROD_DIR'" >&2
        exit 1
    fi
    if [ ! -d "$PROD_DIR/.git" ]; then
        git clone "$REPO_URL" "$PROD_DIR"
    fi

    cd "$PROD_DIR"
    git fetch --tags || echo "Warning: network fetch failed, proceeding with local tags only"
    TOP_TAG=$(git tag -l 'v[0-9]*' --sort=-v:refname | grep -v '-' | head -n 1 2>/dev/null || true)
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
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv &> /dev/null; then
        if command -v brew &> /dev/null; then
            brew install uv
        else
            echo "brew not found, attempting to install uv via standalone installer..."
            curl -LsSf https://astral.sh/uv/install.sh | sh
        fi
        hash -r 2>/dev/null || true
    fi

    uv sync --frozen --no-dev

    # Register and enable macOS launchd service
    PLIST_PATH="$HOME/Library/LaunchAgents/com.localbrain.api.plist"
    echo "Registering macOS LaunchAgent to $PLIST_PATH..."

    # Fallback to read LOCAL_API_KEY from production .env if it exists and is not currently set
    if [ -z "$LOCAL_API_KEY" ] && [ -f "$PROD_DIR/.env" ]; then
        LOCAL_API_KEY="$(${PYTHON:-python3} "$INSTALL_HELPERS" read_env_key "$PROD_DIR/.env")"
    fi

    if [ -z "$LOCAL_API_KEY" ]; then
        echo "Error: LOCAL_API_KEY environment variable is not set. It is required for the production service." >&2
        exit 1
    fi

    # Copy the .env file or create one if it doesn't exist
    if [ -f "$PROD_DIR/.env" ]; then
        echo "Warning: Production .env already exists at $PROD_DIR/.env. Skipping copy."
        _upsert_api_key "$PROD_DIR/.env"
    else
        # Pre-create the file with secure permissions to prevent permission race condition
        touch "$PROD_DIR/.env"

        if [ -f "$ENV_FILE" ]; then
            if [ "$ENV_FILE" -ef "$PROD_DIR/.env" ]; then
                echo "ENV_FILE is the same file as PROD_DIR/.env -- updating or appending LOCAL_API_KEY in place."
                _upsert_api_key "$PROD_DIR/.env"
            else
                cp "$ENV_FILE" "$PROD_DIR/.env"
                _upsert_api_key "$PROD_DIR/.env"
            fi
        else
            _write_env_key > "$PROD_DIR/.env"
        fi
    fi
    chmod 600 "$PROD_DIR/.env"

    # Copy the LaunchAgent plist to the LaunchAgents directory
    mkdir -p "$HOME/Library/LaunchAgents"
    ${PYTHON:-python3} "$INSTALL_HELPERS" write_plist "$PROD_DIR/com.localbrain.api.plist" "$PLIST_PATH" "$HOME"

    # Check if GUI session or user session is available before registering the service
    if launchctl print "gui/$(id -u)" &>/dev/null; then
        # Unload existing instance if present
        launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
        # Load the fresh agent
        launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
    elif launchctl print "user/$(id -u)" &>/dev/null; then
        # Unload existing instance if present
        launchctl bootout "user/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
        # Load the fresh agent
        launchctl bootstrap "user/$(id -u)" "$PLIST_PATH"
    else
        echo "Warning: Neither GUI nor user session available for user $(id -u). LaunchAgent was not registered."
    fi

    echo "Installation and persistent background registration complete."
fi
