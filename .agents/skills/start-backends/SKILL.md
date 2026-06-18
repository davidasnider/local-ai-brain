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

# Extract backend ports from config so servers match the gateway's expectations
read LLM_PORT STT_PORT TTS_PORT <<<$(uv run python -c "from local_ai_brain.config import settings; from urllib.parse import urlparse; print(f\"{urlparse(settings.VLLM_URL).port or 8001} {urlparse(settings.STT_URL).port or 8002} {urlparse(settings.TTS_URL).port or 8003}\")" 2>/dev/null || echo "8001 8002 8003")

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

# LLM Server
uv run python -m local_ai_brain.models.llm_server --host 127.0.0.1 --port "$LLM_PORT" &
LLM_PID=$!
sleep 1
if ! kill -0 "$LLM_PID" 2>/dev/null; then
  echo "❌ LLM Server failed to start!"
  cleanup 1
fi

# STT Server
uv run uvicorn local_ai_brain.models.stt_server:app --host 127.0.0.1 --port "$STT_PORT" &
STT_PID=$!
sleep 1
if ! kill -0 "$STT_PID" 2>/dev/null; then
  echo "❌ STT Server failed to start!"
  cleanup 1
fi

# TTS Server
uv run uvicorn local_ai_brain.models.tts_server:app --host 127.0.0.1 --port "$TTS_PORT" &
TTS_PID=$!
sleep 1
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

  # Check for unexpected stops
  for pid in "$LLM_PID" "$STT_PID" "$TTS_PID"; do
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      echo "❌ Backend process $pid has stopped unexpectedly!"
      cleanup 1
    fi
  done
done
```

