# Product Requirements Document (PRD): Local AI Brain

## 1. Project Overview
A highly responsive, unified local AI API hosted on a Mac Mini (Apple Silicon). This service acts as the central "brain" for home automation (specifically Home Assistant), document processing, and a backend for local agentic coding. It wraps `vllm-mlx` and MLX-optimized audio models in a FastAPI backend, exposing an OpenAI-compatible interface.

## 2. Core Requirements & Constraints
* **Framework:** Python 3.11+ with FastAPI.
* **Configuration:** Strict environment variable validation using `pydantic-settings` (fail-fast on startup).
* **Hardware Limit:** Must strictly cap unified memory usage at **48GB maximum**.
* **Model State:** All primary models (LLM, STT, TTS) remain loaded in memory 24/7 for instant, low-latency responses.
* **Security:** Must implement a single static API Key via `Bearer` token in the HTTP headers to prevent rogue local network access.
* **Observability & Telemetry:** * Granular logging using `loguru` and system monitoring with `psutil` to track RAM usage per request.
  * Must expose an OpenTelemetry (OTEL) Prometheus `/metrics` endpoint for local network scraping.
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
  * Unauthenticated (or lightweight auth) endpoint exposing OTEL Prometheus metrics (token speed, latency, RAM usage).

## 5. Memory Management
* The FastAPI app must include a lightweight middleware or background monitor to track the memory footprint of the loaded MLX arrays. 
* If a request's context window threatens to push the unified memory past the 48GB cap, the API should safely reject the request or truncate context rather than crashing the system.

## 6. Development Environment & Tooling
* **Package Management:** `uv` will be used for all project and dependency management.
* **Linting & Formatting:** `ruff` will be the sole tool for both linting and formatting.
* **Pre-commit Hooks:** The repository must include a `.pre-commit-config.yaml` to enforce quality checks before any code is committed. The hooks must include:
  * **Secret Scanning:** To ensure the local API key is never committed.
  * **Auto-formatting & Linting:** Running `ruff`.
  * **Fast Local Tests:** Triggering a lightweight `pytest` suite for the FastAPI endpoints.


## 7. Interactive CLI
* An interactive CLI tool (`local-brain`) must be provided for directly interacting with and testing the API endpoints.
* It should be built using only standard Python libraries (e.g., `urllib.request`) to minimize dependencies.
* Must support standard chat functionality, plus special commands for testing TTS (`/tts`) and STT (`/stt`).
