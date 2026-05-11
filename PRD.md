# Product Requirements Document (PRD): Local AI Brain

## 1. Project Overview
A highly responsive, unified local AI API hosted on a Mac Mini (Apple Silicon). This service acts as the central "brain" for home automation (specifically Home Assistant), document processing, and a backend for local agentic coding. It uses a microservices architecture with a FastAPI API Gateway proxy in front of dedicated `vllm-mlx` (LLM), Whisper (STT), and Kokoro (TTS) backend services, exposing a unified OpenAI-compatible interface.

## 2. Core Requirements & Constraints
* **Framework:** Python 3.12+ with FastAPI.
* **Configuration:** Strict environment variable validation using `pydantic-settings` (fail-fast on startup).
* **Audio Constraints:** Text-to-Speech (TTS) input length must be restricted by the configurable `TTS_MAX_CHARACTERS` setting (defaults to 4096) to prevent extended blocking of resources.
* **Model State:** All primary models (LLM, STT, TTS) remain loaded in memory 24/7 for instant, low-latency responses.
* **Security:** Must implement a single static API Key via `Bearer` token in the HTTP headers to prevent rogue local network access.
* **Observability & Telemetry:**
  * Granular logging using `loguru` (including file rotation) and background system monitoring via `psutil` observable gauges for process and system memory usage.
  * Must expose a Prometheus `/metrics` endpoint instrumented via OpenTelemetry SDK (`opentelemetry-exporter-prometheus`) for local network scraping. This endpoint tracks detailed metrics like `http_requests_total`, `llm_active_requests`, `llm_tokens_consumed_total`, `llm_tokens_generated_total`, generation latencies, and process/system memory usage.
* **Resilience:** Include a macOS `launchd` `.plist` template to ensure the service automatically starts on boot.

## 3. Core Models
* **Text/Reasoning/Vision (LLM):** Qwen 3.6 (e.g., 35B parameter) quantized for MLX (4-bit to respect RAM limits). Must use a patched `vllm-mlx` implementation (via `src/local_ai_brain/models/llm_server.py`) that defaults prefill chunking to `prefill_step_size=128` and limits default concurrency to `max_num_seqs=1` unless explicitly set otherwise, while also serializing requests at the API gateway level (via semaphore) to reduce macOS Metal watchdog timeout risk.
* **Speech-to-Text (STT):** Lightning Whisper MLX.
* **Text-to-Speech (TTS):** Kokoro TTS via MLX (or ONNX).

## 4. API Endpoints
All functional endpoints must be authenticated via Bearer token (`LOCAL_API_KEY`).

* **`POST /v1/chat/completions`**
  * Fully OpenAI-compatible schema.
  * Handles multi-turn chat, tool calling, and vision inputs.
  * Primary interface for coding tools (Hermes, Gemini CLI) and Home Assistant (via Extended OpenAI integration).

* **`POST /v1/audio/transcriptions`**
  * OpenAI-compatible schema for STT.
  * Accepts audio files and returns highly accurate transcriptions using Whisper.

* **`POST /v1/audio/speech`**
  * Custom OpenAI-style TTS endpoint.
  * **Special Feature - Voice Router:** Must accept a custom parameter in the payload (e.g., `character` or `season`) to dynamically swap Kokoro voice profiles on the fly (e.g., Default, Santa, Irish, Jack Skellington).

* **`GET /metrics`**
  * Authenticated endpoint requiring the same Bearer token (`LOCAL_API_KEY`) as other protected routes, exposing Prometheus metrics instrumented via OpenTelemetry SDK (`opentelemetry-exporter-prometheus`). These include detailed metrics such as `http_requests_total`, token counts, active requests, generation latencies, and process/system memory usage.

## 5. Development Environment & Tooling
* **Package Management:** `uv` will be used for all project and dependency management.
* **Linting & Formatting:** `ruff` will be the sole tool for both linting and formatting.
* **Pre-commit Hooks:** The repository must include a `.pre-commit-config.yaml` to enforce quality checks before any code is committed. The hooks must include:
  * **Secret Scanning:** To ensure the local API key is never committed.
  * **Auto-formatting & Linting:** Running `ruff`.
  * **Fast Local Tests:** Triggering a lightweight `pytest` suite for the FastAPI endpoints.


## 6. Interactive CLI
* An interactive CLI tool (`local-brain`) must be provided for directly interacting with and testing the API endpoints.
* It should be built using only standard Python libraries (e.g., `urllib.request`) to minimize dependencies.
* Must support standard chat functionality, plus special commands for testing TTS (`/tts`) and STT (`/stt`).
