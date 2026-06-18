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

# LLM Server (port 8001)
PYTHONPATH=src uv run python -m local_ai_brain.models.llm_server --host 127.0.0.1 --port 8001 &
LLM_PID=$!

# STT Server (port 8002)
PYTHONPATH=src uv run uvicorn local_ai_brain.models.stt_server:app --host 127.0.0.1 --port 8002 &
STT_PID=$!

# TTS Server (port 8003)
PYTHONPATH=src uv run uvicorn local_ai_brain.models.tts_server:app --host 127.0.0.1 --port 8003 &
TTS_PID=$!

echo "✅ LLM Server (pid $LLM_PID) on 127.0.0.1:8001"
echo "✅ STT Server (pid $STT_PID) on 127.0.0.1:8002"
echo "✅ TTS Server (pid $TTS_PID) on 127.0.0.1:8003"
echo ""
echo "Backend services are running. Start the dev gateway with:"
echo "  PYTHONPATH=src uv run uvicorn local_ai_brain.main:app --host 0.0.0.0 --port 8888 --reload"
echo ""

# Trap Ctrl+C and clean up
cleanup() {
  echo ""
  echo "🛑 Shutting down backend services..."
  kill $LLM_PID $STT_PID $TTS_PID 2>/dev/null || true
  wait
  echo "✅ All backend services stopped."
  exit 0
}
trap cleanup INT TERM

# Wait for all background processes to exit
wait
```
