# Product Requirements Document (PRD): Local AI Brain

## 1. Project Overview
A highly responsive, unified local AI API hosted on a Mac Mini (Apple Silicon). This service acts as the central "brain" for home automation (specifically Home Assistant), document processing, and a backend for local agentic coding. It wraps `vllm-mlx` and MLX-optimized audio models in a FastAPI backend, exposing an OpenAI-compatible interface.

## 2. Core Requirements & Constraints
* **Framework:** Python 3.12+ with FastAPI.
* **Configuration:** Strict environment variable validation using `pydantic-settings` (fail-fast on startup).
* **Hardware Limit:** Must strictly cap unified memory usage at **48GB maximum**.
* **Audio Constraints:** Text-to-Speech (TTS) input length must be restricted by the configurable `TTS_MAX_CHARACTERS` setting (defaults to 4096) to prevent extended blocking of resources.
* **Model State:** All primary models (LLM, STT, TTS) remain loaded in memory 24/7 for instant, low-latency responses.
* **Security:** Must implement a single static API Key via `Bearer` token in the HTTP headers to prevent rogue local network access.
* **Observability & Telemetry:**
  * Granular logging using `loguru` (including file rotation) and system monitoring with `psutil` to track RAM usage per request.
  * Must expose a Prometheus `/metrics` endpoint (via `prometheus_client`) for local network scraping. This endpoint tracks detailed metrics like `http_requests_total`, `llm_active_requests`, `llm_tokens_consumed_total`, `llm_tokens_generated_total`, and process/system memory usage.
* **Resilience:** Include a macOS `launchd` `.plist` template to ensure the service automatically starts on boot.

## 3. Core Models
* **Text/Reasoning/Vision (LLM):** Qwen 3.6 (e.g., 27B parameter) quantized for MLX (4-bit or 8-bit to respect RAM limits).
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
  * Authenticated endpoint requiring the same Bearer token (`LOCAL_API_KEY`) as other protected routes, exposing Prometheus metrics (via `prometheus_client`). These include detailed metrics such as `http_requests_total`, token counts, active requests, generation latencies, and memory rejections.

## 5. Memory Management
* The FastAPI app must include a memory guard middleware (`MemoryGuardMiddleware`) to track the unified memory footprint using `psutil`.
* If a request's projected memory usage (current + estimated payload size) threatens to push the unified memory past the 48GB limit, the API should safely reject the request with a `429 Too Many Requests` error rather than crashing the system, incrementing the `memory_rejections_total` metric.

## 6. Development Environment & Tooling
* **Package Management:** `uv` will be used for all project and dependency management.
* **Linting & Formatting:** `ruff` will be the sole tool for both linting and formatting.
* **Pre-commit Hooks:** The repository must include a `.pre-commit-config.yaml` to enforce quality checks before any code is committed. The hooks must include:
  * **Secret Scanning:** To ensure the local API key is never committed.
  * **Auto-formatting & Linting:** Running `ruff`.
  * **Fast Local Tests:** Triggering a lightweight `pytest` suite for the FastAPI endpoints.
