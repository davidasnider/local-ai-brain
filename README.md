# Local AI Brain

A highly responsive, unified local AI API hosted on Apple Silicon (MLX). This service acts as the central "brain" for home automation (specifically Home Assistant), document processing, and a backend for local agentic coding.

It wraps `vllm-mlx` and MLX-optimized audio models in a FastAPI backend, exposing an OpenAI-compatible interface.

## Core Capabilities

- **LLM (Text/Reasoning/Vision):** Qwen 3.6 35B quantized for MLX (4-bit/8-bit).
- **STT (Speech-to-Text):** Lightning Whisper MLX for high-speed transcription.
- **TTS (Text-to-Speech):** Kokoro TTS via ONNX with custom dynamic voice routing. Input length is restricted by the `TTS_MAX_CHARACTERS` setting (defaults to 4096).
- **Unified Memory Management:** Strictly caps memory usage at **48GB** using a memory guard middleware to ensure system stability. Large requests are proactively rejected if projected to exceed the limit.
- **Observability:** Granular logging with `loguru` directly to file and a robust Prometheus `/metrics` endpoint.
- **Security:** Authenticated via a static `LOCAL_API_KEY` Bearer token.

## Prerequisites

- **OS:** macOS (Apple Silicon strongly recommended).
- **Dependency Manager:** `uv` (will be installed automatically by scripts if missing).
- **Environment:** A `LOCAL_API_KEY` must be set in your environment.

## Installation & Deployment

### Production Installation
The easiest way to deploy Local AI Brain in a persistent manner on macOS is using the provided installation script:

```bash
./scripts/install_prod.sh
```

This script will:
1. Clone the repository to `~/.local/share/local-ai-brain-prod`.
2. Sync dependencies using `uv`.
3. Register and enable a macOS `launchd` service (`com.localbrain.api.plist`) to ensure the API starts on boot and restarts if it crashes.

### Manual Server Start
If you prefer to run the server manually:

```bash
./scripts/start_server.sh
```

The server will be available at `http://localhost:8000`.

## Local Development & Testing

1. **Setup Environment:**
   ```bash
   uv sync
   ```

2. **Run Tests:**
   ```bash
   uv run pytest
   ```

3. **Linting & Formatting:**
   ```bash
   uv run ruff check .
   uv run ruff format .
   ```

## API Usage & Examples

All requests must include the `Authorization: Bearer <LOCAL_API_KEY>` header.

### Chat Completions (OpenAI Compatible)
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LOCAL_API_KEY" \
  -d '{
    "model": "mlx-community/Qwen3.6-35B-A3B-8bit",
    "messages": [{"role": "user", "content": "How do I build a DIY smart mirror?"}],
    "stream": true
  }'
```

### Audio Transcription (Whisper)
```bash
curl http://localhost:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer $LOCAL_API_KEY" \
  -F "file=@path/to/audio.wav"
```

### Text-to-Speech (Kokoro)
The TTS endpoint supports standard parameters plus custom voice routing via `character` or `season`.

```bash
curl http://localhost:8000/v1/audio/speech \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LOCAL_API_KEY" \
  -d '{
    "model": "kokoro-onnx",
    "input": "The weather is lovely in the Shire today.",
    "voice": "af_heart",
    "character": "jack_skellington"
  }' \
  --output speech.wav
```

## Integration Notes

### Upstream Tools (Hermes, Gemini CLI, etc.)
To use Local AI Brain as a backend for tools like Hermes or Gemini CLI, set the base URL and API key in your environment or configuration:

```bash
export OPENAI_API_BASE="http://localhost:8000/v1"
export OPENAI_API_KEY="<your-secret-local-api-key>"
```

### Home Assistant
Use the [Extended OpenAI Conversation](https://github.com/jekalmin/extended_openai_conversation) integration and point it to:
- **URL:** `http://<your-mac-ip>:8000/v1`
- **API Key:** `<LOCAL_API_KEY>`

## Monitoring
Metrics are exposed at `/metrics` in Prometheus format, covering HTTP requests, active LLM requests, token consumption and generation, processing latency, memory rejections, and precise system and process RAM usage.
