# Agent Instructions for Local AI Brain

## Role
You are an expert Python backend engineer specializing in Apple Silicon (MLX), `vllm-mlx`, and FastAPI. Your goal is to build a robust, memory-conscious, secure, and blazing-fast local API.

## Tech Stack
* Python 3.12+
* FastAPI & Uvicorn
* `pydantic-settings` (for configuration)
* `vllm-mlx` (for Qwen 3.6 LLM hosting)
* `mlx-whisper` / Lightning Whisper MLX
* `kokoro-onnx` or native MLX implementation of Kokoro TTS
* `loguru` (logging) & `psutil` (hardware monitoring)
* OpenTelemetry (metrics)
* `uv`, `ruff`, `pre-commit`, and `pytest`

## Core Directives

1. **Tooling & Setup:**
   * Initialize the project using `uv init`. 
   * Manage all dependencies strictly through `uv add`. 
   * Configure `ruff` in `pyproject.toml` to handle both linting and formatting (auto-fix enabled). 
   * Set up `.pre-commit-config.yaml` to include secret scanning, `ruff`, and a fast local `pytest` run.
   * Use `uv sync` to keep the environment updated.

2. **Configuration Management:**
   * Use `pydantic-settings` to manage all configuration. Key settings include (but are not limited to): `LOCAL_API_KEY`, `TTS_MAX_CHARACTERS`, model paths (`QWEN_MODEL_PATH`, `WHISPER_MODEL_PATH`, `KOKORO_MODEL_PATH`), microservice URLs (`VLLM_URL`, `STT_URL`, `TTS_URL`), token limits (`MAX_CONTEXT_TOKENS`, `DEFAULT_MAX_TOKENS`), and LLM cache settings (`LLM_KV_CACHE_BITS`, `LLM_KV_CACHE_QUANTIZATION`).
   * The application must fail fast on startup if the API key or critical configurations are missing.

3. **OpenAI Compatibility & Security:**
   * Ensure `/v1/chat/completions` and audio endpoints perfectly match the OpenAI Pydantic schemas. 
   * Implement a global `Depends` in FastAPI that checks for a valid `Bearer` token matching the `LOCAL_API_KEY`. 
   * All routes — including `/health` and `/metrics` — must require a valid Bearer token. There are no unauthenticated endpoints.

4. **Logging (Crucial):**
   * Ensure model quantization configurations (e.g., 4-bit) are set explicitly during MLX model initialization.
   * Standard library logging should be intercepted and routed to `loguru`, with rotating log files configured.
   * Models must remain loaded 24/7.

5. **Dynamic TTS Routing:**
   * Build a simple dictionary/router for the Kokoro TTS endpoint that maps "season" or "character" string parameters to their respective Kokoro voice embedding files.

6. **Telemetry Endpoint:**
   * Expose a `/metrics` route using OpenTelemetry and `opentelemetry-exporter-prometheus`. Track precise metrics: `http_requests_total`, `llm_active_requests`, `llm_tokens_consumed_total`, `llm_tokens_generated_total`, latencies, and process/system memory consumption. The endpoint requires Bearer token authentication like all other routes.

7. **Background Service:**
   * Write a `com.localbrain.api.plist` template file in the repository root so the user can easily install it via `launchctl` for 24/7 uptime on macOS.

8. **Code Style:**
   * Write clean, asynchronous (`async def`) Python code. 
   * Use dependency injection for model loading to ensure models load on startup and stay hot in memory, rather than reloading on each request.

9. **Interactive CLI Tool:**
   * Maintain the `local-brain` CLI tool located in `src/local_ai_brain/cli.py`.
   * When modifying or adding features to this tool, rely strictly on standard Python libraries (like `urllib.request`) to avoid inflating the project's dependency footprint.

10. **LLM Execution & GPU Timeout Prevention:**
    * Always run `vllm-mlx` ensuring stability overrides (e.g., `--prefill-step-size` and `--max-num-seqs`) are passed via CLI arguments (as configured in `src/local_ai_brain/cli.py`) to prevent macOS Metal watchdog timeouts during large model prefill operations on Apple Silicon.
