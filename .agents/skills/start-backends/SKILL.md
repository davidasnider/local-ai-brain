---
name: start-backends
description: Starts the LLM, STT, and TTS backend microservices individually without the production API Gateway on port 8000. Use when running the development gateway (port 8888) via run-dev and need inference to work.
---

Starts the three backend microservices (LLM on 8001, STT on 8002, TTS on 8003) as background processes in a single terminal. Does NOT start the production API Gateway on port 8000, so it pairs cleanly with the `run-dev` development gateway on port 8888.

Press `Ctrl+C` to gracefully shut down all backend services.

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=""
_dir="$(pwd)"
while [ "$_dir" != "/" ]; do
  if [ -f "$_dir/pyproject.toml" ]; then
    PROJECT_ROOT="$_dir"
    break
  fi
  _dir="$(dirname "$_dir")"
done
if [ -z "$PROJECT_ROOT" ]; then echo "ERROR: Could not find project root" >&2; exit 1; fi
cd "$PROJECT_ROOT"
mkdir -p "$PROJECT_ROOT/.logs"

echo "🔄 Starting backend microservices (LLM, STT, TTS)..."
echo "These will run alongside the dev gateway on port 8888."
echo "Press Ctrl+C to stop all services."
echo ""

# Source environment variables from .env (if present)
# Use Python to parse .env safely — handles inline comments and
# whitespace around '=' that bash sourcing would mangle.
if [ -f .env ]; then
  eval "$(uv run python << 'PYEOF'
import shlex
import re
from dotenv import dotenv_values
for k, v in dotenv_values(".env").items():
    if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", k):
        print(f"export {k}={shlex.quote(v)}")
PYEOF
)"
fi

_check_port() {
  local _port="$1"
  local _host="${2:-127.0.0.1}"
  [[ "$_port" =~ ^[0-9]+$ ]] || return 1
  # Use python3 directly (not uv run) for port check — only stdlib is needed,
  # so uv's lockfile-validation overhead is unnecessary. In tight startup
  # loops this runs up to 90 times; the overhead of uv run is significant.
  python3 -c "import socket,sys; s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(2); s.connect((sys.argv[1], int(sys.argv[2]))); s.close()" "$_host" "$_port" 2>/dev/null
}

# Fail fast if LOCAL_API_KEY is not set (required for config module)
if [ -z "${LOCAL_API_KEY:-}" ]; then
  echo "❌ LOCAL_API_KEY is not set. Set it in .env or export it before running." >&2
  exit 1
fi

export PYTHONPATH=src

# Ports match the defaults in local_ai_brain.config.Settings (llm_config.yaml does not store ports)
# Respect env overrides so users can customize via .env or export (finding #3)
LLM_PORT="${LLM_PORT:-8001}"
STT_PORT="${STT_PORT:-8002}"
TTS_PORT="${TTS_PORT:-8003}"

# Export matching URL variables so the API Gateway connects to the right ports.
# If a user overrides LLM_PORT but not VLLM_URL, this keeps them in sync.
# Explicit VLLM_URL/STT_URL/TTS_URL env overrides are respected as-is.
export VLLM_URL="${VLLM_URL:-http://127.0.0.1:$LLM_PORT}"
export STT_URL="${STT_URL:-http://127.0.0.1:$STT_PORT}"
export TTS_URL="${TTS_URL:-http://127.0.0.1:$TTS_PORT}"

# Initialize PID variables to avoid unbound variable errors in cleanup trap
LLM_PID=""
STT_PID=""
TTS_PID=""

# Trap Ctrl+C and clean up
cleanup() {
  local exit_code="${1:-$?}"
  trap - EXIT INT TERM
  # Check if any services were started at all
  if [ -n "$LLM_PID" ] || [ -n "$STT_PID" ] || [ -n "$TTS_PID" ]; then
    echo ""
    echo "🛑 Shutting down backend services..."
    for pid in "$LLM_PID" "$STT_PID" "$TTS_PID"; do
      [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    done
    for ((_i=0; _i<10; _i++)); do
      if { [ -z "$LLM_PID" ] || ! kill -0 "$LLM_PID" 2>/dev/null; } && \
         { [ -z "$STT_PID" ] || ! kill -0 "$STT_PID" 2>/dev/null; } && \
         { [ -z "$TTS_PID" ] || ! kill -0 "$TTS_PID" 2>/dev/null; }; then
        break
      fi
      sleep 1
    done
    for pid in "$LLM_PID" "$STT_PID" "$TTS_PID"; do
      [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
    done
    echo "✅ All backend services stopped."
  fi
  exit "$exit_code"
}
trap "cleanup 130" INT
trap "cleanup 143" TERM
# Also clean up on shell exit (SIGHUP, window close, set -e) so background
# servers aren't orphaned if the terminal closes unexpectedly (finding #4)
trap cleanup EXIT

# Pre-check port occupancy before starting services (finding #5)
for _port in "$LLM_PORT" "$STT_PORT" "$TTS_PORT"; do
  if _check_port "$_port"; then
    echo "❌ Port $_port is already in use. Conflicting service detected." >&2
    exit 1
  fi
done

# LLM Server
LOG_PATH="$PROJECT_ROOT/.logs/localbrain-llm.log"
uv run python -m local_ai_brain.models.llm_server --host 127.0.0.1 --port "$LLM_PORT" > "$LOG_PATH" 2>&1 &
LLM_PID=$!
for ((_i=0; _i<${BACKEND_STARTUP_TIMEOUT:-30}; _i++)); do
  if _check_port "$LLM_PORT"; then
    break
  fi
  if ! kill -0 "$LLM_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! _check_port "$LLM_PORT"; then
  if kill -0 "$LLM_PID" 2>/dev/null; then
    echo "❌ LLM Server failed to become ready (timeout)!"
  else
    echo "❌ LLM Server crashed (log: $LOG_PATH)"
  fi
  cleanup 1
fi


# STT Server
LOG_PATH="$PROJECT_ROOT/.logs/localbrain-stt.log"
uv run uvicorn local_ai_brain.models.stt_server:app --host 127.0.0.1 --port "$STT_PORT" > "$LOG_PATH" 2>&1 &
STT_PID=$!
for ((_i=0; _i<${BACKEND_STARTUP_TIMEOUT:-30}; _i++)); do
  if _check_port "$STT_PORT"; then
    break
  fi
  if ! kill -0 "$STT_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! _check_port "$STT_PORT"; then
  if kill -0 "$STT_PID" 2>/dev/null; then
    echo "❌ STT Server failed to become ready (timeout)!"
  else
    echo "❌ STT Server crashed (log: $LOG_PATH)"
  fi
  cleanup 1
fi


# TTS Server
LOG_PATH="$PROJECT_ROOT/.logs/localbrain-tts.log"
uv run uvicorn local_ai_brain.models.tts_server:app --host 127.0.0.1 --port "$TTS_PORT" > "$LOG_PATH" 2>&1 &
TTS_PID=$!
for ((_i=0; _i<${BACKEND_STARTUP_TIMEOUT:-30}; _i++)); do
  if _check_port "$TTS_PORT"; then
    break
  fi
  if ! kill -0 "$TTS_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! _check_port "$TTS_PORT"; then
  if kill -0 "$TTS_PID" 2>/dev/null; then
    echo "❌ TTS Server failed to become ready (timeout)!"
  else
    echo "❌ TTS Server crashed (log: $LOG_PATH)"
  fi
  cleanup 1
fi


echo "✅ LLM Server (pid $LLM_PID) on 127.0.0.1:$LLM_PORT"
echo "✅ STT Server (pid $STT_PID) on 127.0.0.1:$STT_PORT"
echo "✅ TTS Server (pid $TTS_PID) on 127.0.0.1:$TTS_PORT"
echo ""
echo "Backend services are running. Start the dev gateway with:"
echo "  PYTHONPATH=src uv run uvicorn local_ai_brain.main:app --host 127.0.0.1 --port 8888 --reload"
echo ""

# Monitor backend processes until one fails or all exit
while true; do
  sleep 3

  # Check for unexpected stops — use wait to get exit code and
  # differentiate clean exit from crash (finding #1)
  for _var in LLM_PID STT_PID TTS_PID; do
    _pid="${!_var}"
    if [ -n "$_pid" ] && ! kill -0 "$_pid" 2>/dev/null; then
      _exit_code=0
      wait "$_pid" 2>/dev/null || _exit_code=$?
      if [ "$_exit_code" = 0 ]; then
        echo "⚠ Backend process $_pid ($_var) exited cleanly (code 0). Continuing with remaining services."
        printf -v "$_var" ''
      else
        echo "❌ Backend process $_pid ($_var) stopped unexpectedly (exit code $_exit_code)!"
        cleanup 1
      fi
    fi
  done

  # Check if all PIDs have exited (processes finished cleanly)
  all_done=true
  for pid in "$LLM_PID" "$STT_PID" "$TTS_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      all_done=false
      break
    fi
  done
  if [ "$all_done" = true ]; then
    break
  fi
done
```

Note: These scripts do not have automated tests. ShellCheck and manual smoke tests are recommended before deploying changes.

