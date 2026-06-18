---
name: start-backends
description: Starts the LLM, STT, and TTS backend microservices individually without the production API Gateway on port 8000. Use when running the development gateway (port 8888) via run-dev and need inference to work.
---

Starts the three backend microservices (LLM on 8001, STT on 8002, TTS on 8003) as background processes in a single terminal. Does NOT start the production API Gateway on port 8000, so it pairs cleanly with the `run-dev` development gateway on port 8888.

Press `Ctrl+C` to gracefully shut down all backend services.

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "🔄 Starting backend microservices (LLM, STT, TTS)..."
echo "These will run alongside the dev gateway on port 8888."
echo "Press Ctrl+C to stop all services."
echo ""

# Source environment variables from .env (if present)
if [ -f .env ]; then
  set -a && source .env && set +a
fi

export PYTHONPATH=src

# Initialize PID variables to avoid unbound variable errors in cleanup trap
LLM_PID=""
STT_PID=""
TTS_PID=""

# Trap Ctrl+C and clean up
cleanup() {
  local exit_code="${1:-0}"
  echo ""
  echo "🛑 Shutting down backend services..."
  for pid in "$LLM_PID" "$STT_PID" "$TTS_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait || true
  echo "✅ All backend services stopped."
  exit "$exit_code"
}
trap cleanup INT TERM

# LLM Server (port 8001)
uv run python -m local_ai_brain.models.llm_server --host 127.0.0.1 --port 8001 &
LLM_PID=$!
sleep 1
if ! kill -0 "$LLM_PID" 2>/dev/null; then
  echo "❌ LLM Server failed to start!"
  cleanup 1
fi

# STT Server (port 8002)
uv run uvicorn local_ai_brain.models.stt_server:app --host 127.0.0.1 --port 8002 &
STT_PID=$!
sleep 1
if ! kill -0 "$STT_PID" 2>/dev/null; then
  echo "❌ STT Server failed to start!"
  cleanup 1
fi

# TTS Server (port 8003)
uv run uvicorn local_ai_brain.models.tts_server:app --host 127.0.0.1 --port 8003 &
TTS_PID=$!
sleep 1
if ! kill -0 "$TTS_PID" 2>/dev/null; then
  echo "❌ TTS Server failed to start!"
  cleanup 1
fi

echo "✅ LLM Server (pid $LLM_PID) on 127.0.0.1:8001"
echo "✅ STT Server (pid $STT_PID) on 127.0.0.1:8002"
echo "✅ TTS Server (pid $TTS_PID) on 127.0.0.1:8003"
echo ""
echo "Backend services are running. Start the dev gateway with:"
echo "  PYTHONPATH=src uv run uvicorn local_ai_brain.main:app --host 0.0.0.0 --port 8888 --reload"
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
  [ "$all_done" = true ] && break

  # Check for unexpected stops
  for pid in "$LLM_PID" "$STT_PID" "$TTS_PID"; do
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      echo "❌ Backend process $pid has stopped unexpectedly!"
      cleanup 1
    fi
  done
done
```

