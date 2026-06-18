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

echo "🔄 Starting backend microservices (LLM, STT, TTS)..."
echo "These will run alongside the dev gateway on port 8888."
echo "Press Ctrl+C to stop all services."
echo ""

# Source environment variables from .env (if present)
if [ -f .env ]; then
  set -a && source .env && set +a
fi

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

# Initialize PID variables to avoid unbound variable errors in cleanup trap
LLM_PID=""
STT_PID=""
TTS_PID=""

# Trap Ctrl+C and clean up
cleanup() {
  local exit_code="${1:-0}"
  trap - EXIT INT TERM
  echo ""
  echo "🛑 Shutting down backend services..."
  for pid in "$LLM_PID" "$STT_PID" "$TTS_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  for _i in $(seq 10); do
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
  exit "$exit_code"
}
trap "cleanup 130" INT
trap "cleanup 143" TERM
# Also clean up on shell exit (SIGHUP, window close, set -e) so background
# servers aren't orphaned if the terminal closes unexpectedly (finding #4)
trap cleanup EXIT

# Pre-check port occupancy before starting services (finding #5)
for _port in "$LLM_PORT" "$STT_PORT" "$TTS_PORT"; do
  if PORT="$_port" uv run python -c "import os, socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', int(os.environ['PORT'])))" 2>/dev/null; then
    echo "⚠ Port $_port is already in use. Check for conflicting services."
  fi
done

# LLM Server
uv run python -m local_ai_brain.models.llm_server --host 127.0.0.1 --port "$LLM_PORT" &
LLM_PID=$!
for _i in $(seq 30); do
  if PORT="$LLM_PORT" uv run python -c "import os, socket; s=socket.socket(); s.settimeout(0.5); s.connect(('127.0.0.1', int(os.environ['PORT'])))" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$LLM_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! kill -0 "$LLM_PID" 2>/dev/null; then
  echo "❌ LLM Server failed to start!"
  cleanup 1
fi

# STT Server
uv run uvicorn local_ai_brain.models.stt_server:app --host 127.0.0.1 --port "$STT_PORT" &
STT_PID=$!
for _i in $(seq 30); do
  if PORT="$STT_PORT" uv run python -c "import os, socket; s=socket.socket(); s.settimeout(0.5); s.connect(('127.0.0.1', int(os.environ['PORT'])))" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$STT_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! kill -0 "$STT_PID" 2>/dev/null; then
  echo "❌ STT Server failed to start!"
  cleanup 1
fi

# TTS Server
uv run uvicorn local_ai_brain.models.tts_server:app --host 127.0.0.1 --port "$TTS_PORT" &
TTS_PID=$!
for _i in $(seq 30); do
  if PORT="$TTS_PORT" uv run python -c "import os, socket; s=socket.socket(); s.settimeout(0.5); s.connect(('127.0.0.1', int(os.environ['PORT'])))" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$TTS_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! kill -0 "$TTS_PID" 2>/dev/null; then
  echo "❌ TTS Server failed to start!"
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

  # Check for unexpected stops — use wait to get exit code and
  # differentiate clean exit from crash (finding #1)
  for _var in LLM_PID STT_PID TTS_PID; do
    _pid="${!_var}"
    if [ -n "$_pid" ] && ! kill -0 "$_pid" 2>/dev/null; then
      wait "$_pid" 2>/dev/null
      _exit_code=$?
      if [ "$_exit_code" = 0 ]; then
        echo "⚠ Backend process $_pid ($_var) exited cleanly (code 0). Continuing with remaining services."
        eval "$_var="
      else
        echo "❌ Backend process $_pid ($_var) stopped unexpectedly (exit code $_exit_code)!"
        cleanup 1
      fi
    fi
  done
done
```

Note: These scripts do not have automated tests. ShellCheck and manual smoke tests are recommended before deploying changes.

