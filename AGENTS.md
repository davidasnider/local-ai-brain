# Agent Instructions for Local AI Brain

## Role
You are an expert Python backend engineer specializing in Apple Silicon, `llama-cpp-python`, and FastAPI. Your goal is to build a robust, memory-conscious, secure, and blazing-fast local API.

## Tech Stack
* Python 3.12+
* FastAPI & Uvicorn
* `pydantic-settings` (for configuration)
* `llama-cpp-python` (for Qwen 3.6 LLM hosting via llama-server)
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
   * Use `pydantic-settings` to manage all application-level configuration. Key settings include (but are not limited to): `LOCAL_API_KEY`, `TTS_MAX_CHARACTERS`, model paths (`QWEN_MODEL_PATH`, `WHISPER_MODEL_PATH`, `KOKORO_MODEL_PATH`, `QWEN_MODEL_ALIASES`), microservice URLs (`VLLM_URL`, `STT_URL`, `TTS_URL`), token limits (`MAX_CONTEXT_TOKENS`, `DEFAULT_MAX_TOKENS`). LLM runtime tunables (cache type, speculative decoding flags, batch sizes) are configured separately via `llm_config.yaml`.
   * The application must fail fast on startup if the API key or critical configurations are missing.

3. **OpenAI Compatibility & Security:**
   * Ensure `/v1/chat/completions` and audio endpoints perfectly match the OpenAI Pydantic schemas. 
   * Implement a global `Depends` in FastAPI that checks for a valid `Bearer` token matching the `LOCAL_API_KEY`. 
   * All routes — including `/health` and `/metrics` — must require a valid Bearer token. There are no unauthenticated endpoints.
   * Model requests matching `QWEN_MODEL_ALIASES` must be normalized to `QWEN_MODEL_PATH` before proxying to maintain backwards compatibility.
   * Provide Ollama compatibility endpoints (`/api/v1/models` and `/api/tags`) for tools expecting an Ollama backend.
   * Ensure the API dynamically clamps requested `max_tokens` to the maximum supported context size (`MAX_CONTEXT_TOKENS` = 98304) to prevent extremely large values from causing backend generation failures. If `max_tokens` is not provided, default to `DEFAULT_MAX_TOKENS` (16384).

4. **Logging (Crucial):**
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
   * Use the `{model_id:path}` syntax for FastAPI route parameters when accepting model identifiers to properly handle HuggingFace/MLX model names with forward slashes.

9. **Interactive CLI Tool:**
   * Maintain the `local-brain` CLI tool located in `src/local_ai_brain/cli.py`.
   * When modifying or adding features to this tool, rely strictly on standard Python libraries (like `urllib.request`) to avoid inflating the project's dependency footprint.

10. **LLM Execution & GPU Timeout Prevention:**
    * Always run `llama-cpp-python` via the `llama-server` binary wrapper (`src/local_ai_brain/models/llm_server.py`) ensuring stability overrides for Apple Silicon (e.g., `-ngl`, `--ctx-size`, `-fa on`, `--batch-size`, `--ubatch-size`, `-np`, `--spec-draft-n-max`, `--spec-draft-p-min`, `--cache-type-k`, `--cache-type-v`) are parsed from `llm_config.yaml` to prevent macOS Metal watchdog timeouts during large model operations.
    * There is also a standalone utility script available in `scripts/start_llm.sh` to start the `llama-server` wrapper module independently, primarily for testing purposes. It relies on the same defaults and `llm_config.yaml` as the production service.
    * The API Gateway (`src/local_ai_brain/main.py`) must serialize concurrent LLM requests using an `asyncio.Semaphore(1)` so requests queue at the proxy layer rather than overloading the backend.
