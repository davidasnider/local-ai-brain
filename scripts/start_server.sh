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
"$UV_BIN" sync --frozen --no-dev

# Export environment variables for the sub-processes if needed
# We will run them on specific ports and the proxy on 8000

echo "Starting vLLM MLX Server on port 8001..."
PYTHONPATH=src "$UV_BIN" run python -m vllm_mlx.server --host 127.0.0.1 --port 8001 &
VLLM_PID=$!

echo "Starting STT Server on port 8002..."
PYTHONPATH=src "$UV_BIN" run uvicorn local_ai_brain.models.stt_server:app --host 127.0.0.1 --port 8002 &
STT_PID=$!

echo "Starting TTS Server on port 8003..."
PYTHONPATH=src "$UV_BIN" run uvicorn local_ai_brain.models.tts_server:app --host 127.0.0.1 --port 8003 &
TTS_PID=$!

# Function to cleanly kill sub-processes on exit
cleanup() {
    echo "Shutting down servers..."
    kill $VLLM_PID $STT_PID $TTS_PID 2>/dev/null || true
    wait $VLLM_PID $STT_PID $TTS_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting Proxy Server on port 8000..."
export VLLM_URL="http://127.0.0.1:8001"
export STT_URL="http://127.0.0.1:8002"
export TTS_URL="http://127.0.0.1:8003"
PYTHONPATH=src "$UV_BIN" run uvicorn local_ai_brain.main:app --host 0.0.0.0 --port 8000
