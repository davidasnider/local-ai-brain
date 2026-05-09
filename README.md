# Local AI Brain

A highly responsive, unified local AI API hosted on Apple Silicon (MLX). This service acts as the central "brain" for home automation (specifically Home Assistant), document processing, and a backend for local agentic coding.

It uses a microservices architecture: a FastAPI API Gateway proxy sits in front of dedicated `vllm-mlx` (LLM), Whisper (STT), and Kokoro (TTS) backend services, exposing a unified OpenAI-compatible interface.

## Core Capabilities

- **LLM (Text/Reasoning/Vision):** Qwen 3.6 35B quantized for MLX (4-bit). Legacy `*-8bit` model IDs are still accepted as aliases and normalized to the canonical 4-bit model path for compatibility. Uses a custom wrapper (`src/local_ai_brain/models/llm_server.py`) to prevent macOS Metal watchdog timeouts during large prefill operations.
- **STT (Speech-to-Text):** Lightning Whisper MLX for high-speed transcription.
- **TTS (Text-to-Speech):** Kokoro TTS via ONNX with custom dynamic voice routing. Input length is restricted by the `TTS_MAX_CHARACTERS` setting (defaults to 4096).
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
If you prefer to run the server manually, use the built-in CLI orchestrator:

```bash
uv run local-brain serve
```

This command starts all four processes:
- **vLLM MLX** (LLM) on `127.0.0.1:8001` (via `llm_server.py` wrapper to prevent macOS Metal timeouts)
- **STT Server** (Whisper) on `127.0.0.1:8002`
- **TTS Server** (Kokoro) on `127.0.0.1:8003`
- **API Gateway** (Proxy) on `0.0.0.0:8000`

All external traffic flows through the authenticated API Gateway on port `8000`. Backend services are bound to `127.0.0.1` and are not directly accessible from the network. Press `Ctrl+C` to gracefully shut down all services.

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
    "model": "mlx-community/Qwen3.6-35B-A3B-4bit",
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


## CLI Application

Local AI Brain includes an interactive CLI application for testing the local AI models directly from your terminal without needing external tools.

### Running the CLI

You can start the CLI using `uv`:

```bash
uv run local-brain
```

### CLI Features

The CLI connects to your local instance (default: `http://localhost:8000/v1`) and requires the `LOCAL_API_KEY` (or `OPENAI_API_KEY`) to be set in your environment.

Available commands inside the CLI:
- `/help` - Show available commands.
- `/clear` - Clear the current chat history.
- `/tts <text>` - Generate a Text-to-Speech audio file (`speech.wav`).
- `/stt <filepath>` - Transcribe an audio file using Speech-to-Text.
- `/exit` or `quit` - Exit the CLI.
- Standard text input will be treated as a chat message to the LLM.

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
Metrics are exposed at `/metrics` in Prometheus format, covering HTTP requests, active LLM requests, token consumption and generation, processing latency, and precise system and process RAM usage.
