# Local AI Brain

A highly responsive, unified local AI API hosted on Apple Silicon (MLX). This service acts as the central "brain" for home automation (specifically Home Assistant), document processing, and a backend for local agentic coding.

It uses a microservices architecture: a FastAPI API Gateway proxy sits in front of dedicated `llama-cpp-python` (LLM), Whisper (STT), and Kokoro (TTS) backend services, exposing a unified OpenAI-compatible interface.

## Core Capabilities

- **LLM (Text/Reasoning/Vision):** Qwen 3.6 35B quantized (GGUF). The API is backed by the `llama-cpp-python` server. It supports a large **96K context window** (`MAX_CONTEXT_TOKENS` = 98304). It utilizes Flash Attention, KV cache quantization (Q8_0), and optimized batch sizes for maximum performance on Apple Silicon. To ensure stability and prevent timeouts, the `local-brain serve` CLI command manages the server lifecycle, and concurrent requests are serialized at the API Gateway level. Configuration can be overridden via `llm_config.yaml`.
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
- **LLM Server** on `127.0.0.1:8001` (via `llm_server.py` wrapper to prevent macOS Metal timeouts)
- **STT Server** (Whisper) on `127.0.0.1:8002`
- **TTS Server** (Kokoro) on `127.0.0.1:8003`
- **API Gateway** (Proxy) on `0.0.0.0:8000`

All external traffic flows through the authenticated API Gateway on port `8000`. Backend services are bound to `127.0.0.1` and are not directly accessible from the network. 

### Reliability and Logging

The system is designed for high availability on macOS:
- **Auto-Restart:** The `local-brain serve` orchestrator monitors all backend services. If any process crashes, it is automatically restarted after a 5-second delay.
- **Crash Logging:** Subprocess errors (stderr) are captured in a dedicated crash log file: `~/Library/Logs/local-ai-brain-crash.log`.
- **System Logging:** Operational logs are stored in `~/Library/Logs/local-ai-brain.log`.
- **Process Management:** In production, the system is managed by `launchd` via `com.localbrain.api.plist`, providing system-level persistence and auto-start on boot.

Press `Ctrl+C` to gracefully shut down all services.


### Standalone LLM Server
You can also run the underlying `llama-cpp-python` server directly (without the API Gateway or audio services) for testing purposes using the provided shell script:

```bash
./scripts/start_llm.sh
```

This starts the optimized LLM server on `127.0.0.1:8000` using the parameters defined in `llm_server.py` (which can be overridden by editing `llm_config.yaml`).

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
    "model": "unsloth/Qwen3.6-35B-A3B-MTP-GGUF",
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

### Model Alias Normalization & Ollama Compatibility
For backwards compatibility with clients that hardcode legacy model identifiers, the API Gateway inspects JSON payloads on `/v1/chat/completions` and `/v1/completions`. When `model` exactly matches an entry in `QWEN_MODEL_ALIASES`, it rewrites that value to `QWEN_MODEL_PATH` before proxying to the backend.

Additionally, Local AI Brain exposes Ollama compatibility endpoints (`/api/v1/models` and `/api/tags`) to allow tools that expect an Ollama-compatible backend to list and verify available models seamlessly.


### Home Assistant
Use the [Extended OpenAI Conversation](https://github.com/jekalmin/extended_openai_conversation) integration and point it to:
- **URL:** `http://<your-mac-ip>:8000/v1`
- **API Key:** `<LOCAL_API_KEY>`

## Monitoring
Metrics are exposed at `/metrics` in Prometheus format, covering HTTP requests, active LLM requests, token consumption and generation, processing latency, and precise system and process RAM usage.
