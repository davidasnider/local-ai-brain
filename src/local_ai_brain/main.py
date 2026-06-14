import asyncio
import contextlib
import json
import secrets
import time

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import settings
from .logging import configure_logging
from .middleware import MetricsMiddleware

# Standardize logging using our centralized configuration
configure_logging(settings.TESTING)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(HTTPBearer(auto_error=False)),
):
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.LOCAL_API_KEY
    ):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return credentials.credentials


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize a single httpx client for the lifetime of the app
    # Use a long timeout for LLM inference (10 minutes)
    app.state.client = httpx.AsyncClient(timeout=600.0)
    # Semaphore to prevent Metal GPU timeouts by limiting concurrent LLM requests
    app.state.llm_semaphore = asyncio.Semaphore(1)
    yield
    await app.state.client.aclose()


app = FastAPI(
    lifespan=lifespan,
    title="Local AI Brain Gateway",
    dependencies=[Depends(verify_api_key)],
)

# Add Middlewares
app.add_middleware(MetricsMiddleware)


async def proxy_request(request: Request, target_url: str, use_semaphore: bool = False):
    """Proxy the request to a backend service.

    Args:
        request: The incoming FastAPI request.
        target_url: The base URL of the backend service to proxy to.
        use_semaphore: If True, uses the app-level LLM semaphore to serialize requests.
            This is used to prevent Metal GPU timeouts on Apple Silicon.
    """
    path = request.url.path
    query = request.url.query
    url = f"{target_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"

    headers = dict(request.headers)
    # Strip hop-by-hop, content-length, and client auth headers before proxying
    headers_to_strip = [
        "host",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "authorization",
        "content-length",
    ]
    for h in headers_to_strip:
        headers.pop(h, None)

    # Inject internal authentication
    headers["Authorization"] = f"Bearer {settings.LOCAL_API_KEY}"

    should_normalize_model = (
        request.method in {"POST", "PUT"}
        and (path.startswith("/v1/chat/") or path == "/v1/completions")
        and "application/json" in headers.get("content-type", "").lower()
    )

    model_name = "STT/TTS" if not should_normalize_model else "LLM"

    if should_normalize_model:
        body = await request.body()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.debug("Skipping model alias normalization: invalid JSON payload")
            payload = None
        if isinstance(payload, dict):
            model_name = payload.get("model", "LLM")
            if isinstance(model_name, str) and model_name in settings.QWEN_MODEL_ALIASES:
                payload["model"] = settings.QWEN_MODEL_PATH
                model_name = settings.QWEN_MODEL_PATH

            # Always request usage for streaming requests if possible
            if payload.get("stream") is True:
                stream_opts = payload.get("stream_options")
                if isinstance(stream_opts, dict):
                    stream_opts["include_usage"] = True
                else:
                    payload["stream_options"] = {"include_usage": True}

            # Default output token limit and max_tokens clamping handling
            max_tokens = payload.get("max_tokens")
            if max_tokens is None:
                payload["max_tokens"] = settings.DEFAULT_MAX_TOKENS
                logger.debug(f"Defaulting max_tokens to {settings.DEFAULT_MAX_TOKENS}")
            elif isinstance(max_tokens, int):
                if max_tokens > settings.MAX_CONTEXT_TOKENS:
                    logger.debug(
                        f"Clamping requested max_tokens ({max_tokens}) "
                        f"to MAX_CONTEXT_TOKENS ({settings.MAX_CONTEXT_TOKENS})"
                    )
                    payload["max_tokens"] = settings.MAX_CONTEXT_TOKENS

            # Log who is talking
            client_host = request.client.host if request.client else "unknown"
            client_port = request.client.port if request.client else 0
            messages = payload.get("messages", [])
            prompt_preview = ""
            if messages and isinstance(messages, list):
                last_msg_obj = messages[-1]
                if isinstance(last_msg_obj, dict):
                    last_msg = last_msg_obj.get("content", "")
                    if isinstance(last_msg, str):
                        prompt_preview = last_msg[:100].replace("\n", " ") + (
                            "..." if len(last_msg) > 100 else ""
                        )
                    elif isinstance(last_msg, list):
                        # Multi-part content (vision/tooling) — extract text parts
                        text_parts = [
                            part.get("text", "")
                            for part in last_msg
                            if isinstance(part, dict)
                            and part.get("type") == "text"
                            and isinstance(part.get("text"), str)
                        ]
                        combined = " ".join(text_parts)
                        if combined:
                            prompt_preview = combined[:100].replace("\n", " ") + (
                                "..." if len(combined) > 100 else ""
                            )
                        else:
                            prompt_preview = "[multi-part content]"
            elif "prompt" in payload and isinstance(payload["prompt"], str):
                prompt_preview = payload["prompt"][:100].replace("\n", " ") + (
                    "..." if len(payload["prompt"]) > 100 else ""
                )

            if prompt_preview:
                if settings.LOG_PROMPTS:
                    preview = json.dumps(prompt_preview)
                    logger.info(f"Incoming chat from {client_host}:{client_port} - {preview}")
                else:
                    logger.info(
                        f"Incoming chat from {client_host}:{client_port} - [PROMPT REDACTED]"
                    )

            body = json.dumps(payload).encode("utf-8")
        content = body

    else:
        content = request.stream()

    client = request.app.state.client
    req = client.build_request(
        method=request.method,
        url=url,
        headers=headers,
        content=content,
    )

    async def stream_generator(
        response: httpx.Response,
        semaphore: asyncio.Semaphore | None,
        request_start: float,
        model_name: str,
        is_llm: bool = False,
    ):
        first_token_time = None
        usage = None
        try:
            async for chunk in response.aiter_bytes():
                if first_token_time is None:
                    first_token_time = time.perf_counter()

                # Try a quick check for usage in this chunk
                if b'"usage"' in chunk:
                    try:
                        decoded = chunk.decode("utf-8", errors="ignore")
                        # Case 1: Standard SSE format
                        for line in decoded.split("\n"):
                            if line.startswith("data: "):
                                try:
                                    payload = json.loads(line[6:])
                                    if "usage" in payload:
                                        usage = payload["usage"]
                                except Exception:
                                    pass

                        # Case 2: Raw JSON (non-streaming)
                        if not usage:
                            try:
                                payload = json.loads(decoded)
                                if "usage" in payload:
                                    usage = payload["usage"]
                            except json.JSONDecodeError:
                                pass
                    except Exception:
                        pass

                yield chunk
        finally:
            request_end = time.perf_counter()
            try:
                await response.aclose()
            finally:
                if semaphore:
                    semaphore.release()

            # Log LLM usage if we found it or just the total time
            total_time = request_end - request_start
            log_prefix = "[LLM]" if is_llm else "[Proxy]"

            if usage:
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                # Input TPS (Prefill)
                if first_token_time is not None and prompt_tokens > 0:
                    prefill_duration = first_token_time - request_start
                    if prefill_duration > 0.001:
                        input_tps = prompt_tokens / prefill_duration
                        input_tps_str = f"{input_tps:.2f} t/s"
                    else:
                        input_tps_str = "FAST"
                else:
                    input_tps_str = "N/A"

                # Output TPS (Generation)
                if first_token_time is not None and completion_tokens > 1:
                    generation_duration = request_end - first_token_time
                    if generation_duration > 0.01:
                        output_tps = completion_tokens / generation_duration
                        output_tps_str = f"{output_tps:.2f} t/s"
                    else:
                        output_tps_str = "FAST"
                else:
                    output_tps_str = "N/A"

                logger.info(
                    "{} {} completed: {} in ({}) | {} out ({}) | {:.2f}s total",
                    log_prefix,
                    model_name,
                    prompt_tokens,
                    input_tps_str,
                    completion_tokens,
                    output_tps_str,
                    total_time,
                )
            else:
                logger.info(
                    "{} {} completed in {:.2f}s (No usage found)",
                    log_prefix,
                    model_name,
                    total_time,
                )

    semaphore = request.app.state.llm_semaphore if use_semaphore else None
    response = None
    semaphore_acquired = False
    try:
        if semaphore:
            await semaphore.acquire()
            semaphore_acquired = True

        request_start = time.perf_counter()
        response = await client.send(req, stream=True)

        # Build StreamingResponse with multiple headers support
        streaming_resp = StreamingResponse(
            stream_generator(response, semaphore, request_start, model_name, is_llm=use_semaphore),
            status_code=response.status_code,
        )

        # Strip backend-specific hop-by-hop headers from the response
        hop_by_hop_headers = {
            "connection",
            "keep-alive",
            "transfer-encoding",
            "content-length",
            "content-encoding",
        }
        # Use multi_items() if available to preserve duplicate headers like Set-Cookie
        # falling back to items() for basic compatibility.
        headers_source = getattr(response.headers, "multi_items", response.headers.items)
        for key, value in headers_source():
            if key.lower() not in hop_by_hop_headers:
                # Use raw_headers to preserve duplicates (FastAPI/Starlette internal)
                streaming_resp.raw_headers.append(
                    (key.lower().encode("latin-1"), value.encode("latin-1"))
                )

        # Clear flags so finally block doesn't cleanup resources now owned by StreamingResponse
        response = None
        semaphore_acquired = False
        return streaming_resp

    except Exception as e:
        if isinstance(e, httpx.RequestError):
            logger.error(f"Proxy error to {url}: {e}")
            raise HTTPException(status_code=502, detail="Bad Gateway")
        raise
    finally:
        # If we didn't successfully hand off to StreamingResponse, clean up
        try:
            if response:
                await response.aclose()
        finally:
            if semaphore_acquired:
                semaphore.release()


@app.api_route(
    "/v1/chat/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def proxy_vllm_chat(request: Request, path: str):
    return await proxy_request(request, settings.VLLM_URL, use_semaphore=True)


@app.api_route(
    "/v1/completions",
    methods=["GET", "POST"],
)
async def proxy_vllm_completions(request: Request):
    return await proxy_request(request, settings.VLLM_URL, use_semaphore=True)


def normalize_model_metadata(model_obj: dict):
    """Normalize llama-server metadata into standard OpenAI-compatible fields.

    Promotes internal llama.cpp 'n_ctx' to standard fields like 'max_model_len'
    and 'context_window' at the top level, and removes 'n_ctx_train' to prevent
    agents from assuming a larger context window than configured.
    """
    if "meta" in model_obj:
        meta = model_obj["meta"]
        # Use the configured context window (n_ctx) as the source of truth
        n_ctx = meta.get("n_ctx")
        if n_ctx:
            # Promote to top-level fields commonly used by AI clients/proxies
            model_obj["max_model_len"] = n_ctx
            model_obj["context_window"] = n_ctx
            model_obj["max_position_embeddings"] = n_ctx

        # Remove the training context length to prevent confusion
        meta.pop("n_ctx_train", None)

    # Inject project-defined aliases for the primary LLM model
    if model_obj.get("id") == settings.QWEN_MODEL_PATH:
        existing_aliases = model_obj.get("aliases", [])
        for alias in settings.QWEN_MODEL_ALIASES:
            if alias not in existing_aliases:
                existing_aliases.append(alias)
        model_obj["aliases"] = existing_aliases

    return model_obj


async def _fetch_models_data(request: Request):
    """Internal helper to fetch all models and detect if the backend is unreachable."""
    backend_failed = False
    try:
        client = request.app.state.client
        # Add internal auth to backend request and use a short timeout
        headers = {"Authorization": f"Bearer {settings.LOCAL_API_KEY}"}
        vllm_resp = await client.get(f"{settings.VLLM_URL}/v1/models", headers=headers, timeout=5.0)
        vllm_resp.raise_for_status()
        data = vllm_resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch models from LLM backend: {e}")
        data = {"object": "list", "data": []}
        backend_failed = True

    data.setdefault("data", [])

    # Normalize metadata for all LLM models returned by the backend
    data["data"] = [normalize_model_metadata(m) for m in data["data"]]

    data["data"].extend(
        [
            {
                "id": settings.WHISPER_MODEL_PATH,
                "object": "model",
                "created": 1700000000,
                "owned_by": "local-ai-brain",
                "type": "stt",
            },
            {
                "id": settings.KOKORO_MODEL_PATH,
                "object": "model",
                "created": 1700000000,
                "owned_by": "local-ai-brain",
                "type": "tts",
            },
        ]
    )
    return data, backend_failed


@app.get("/v1/models")
async def list_models(request: Request):
    """List available models by merging backend LLM models with local audio models."""
    data, _ = await _fetch_models_data(request)
    return data


@app.get("/v1/models/{model_id:path}")
async def get_model(model_id: str, request: Request):
    """Get details for a specific model."""
    # Normalize model_id (some clients URL-encode it)
    from urllib.parse import unquote

    model_id = unquote(model_id)

    # Check against our local audio models first
    if model_id == settings.WHISPER_MODEL_PATH:
        return {
            "id": model_id,
            "object": "model",
            "created": 1700000000,
            "owned_by": "local-ai-brain",
            "type": "stt",
        }
    elif model_id == settings.KOKORO_MODEL_PATH:
        return {
            "id": model_id,
            "object": "model",
            "created": 1700000000,
            "owned_by": "local-ai-brain",
            "type": "tts",
        }

    # For everything else (including LLMs), we resolve it by querying the combined list
    # Because llama-server doesn't seem to support GET /v1/models/{id} natively.
    models_data, backend_failed = await _fetch_models_data(request)
    for model in models_data.get("data", []):
        if model.get("id") == model_id or model_id in model.get("aliases", []):
            return model

    if backend_failed:
        raise HTTPException(
            status_code=502, detail="LLM backend unreachable. Check if llama-server is running."
        )

    raise HTTPException(status_code=404, detail="Model not found")


# Compatibility endpoints for various LLM clients
@app.get("/api/v1/models")
async def ollama_models_compat(request: Request):
    return await list_models(request)


@app.get("/api/tags")
async def ollama_tags_compat(request: Request):
    data = await list_models(request)
    return {"models": data.get("data", [])}


@app.get("/version")
async def version_compat():
    try:
        import importlib.metadata

        version = importlib.metadata.version("local-ai-brain")
    except Exception:
        version = "0.1.17"  # Fallback
    return {"version": version}


@app.get("/v1/props")
@app.get("/props")
async def props_compat():
    return {"status": "ok", "features": ["chat", "transcription", "speech"]}


@app.post("/v1/audio/transcriptions")
async def proxy_stt(request: Request):
    return await proxy_request(request, settings.STT_URL)


@app.post("/v1/audio/speech")
async def proxy_tts(request: Request):
    return await proxy_request(request, settings.TTS_URL)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "proxy": "active"}


@app.get("/metrics", tags=["System"])
async def get_metrics(request: Request):
    # Expose Prometheus metrics from OpenTelemetry custom registry
    from .metrics import OTEL_REGISTRY

    proxy_metrics = generate_latest(OTEL_REGISTRY)
    combined_metrics = proxy_metrics

    client = request.app.state.client
    headers = {"Authorization": f"Bearer {settings.LOCAL_API_KEY}"}
    for name, url in [
        ("vLLM", settings.VLLM_URL),
        ("STT", settings.STT_URL),
        ("TTS", settings.TTS_URL),
    ]:
        try:
            resp = await client.get(f"{url}/metrics", headers=headers, timeout=2.0)
            if resp.status_code == 200:
                combined_metrics += b"\n" + resp.content
        except Exception as e:
            logger.warning(f"Failed to fetch metrics from {name} at {url}: {e}")

    return Response(combined_metrics, media_type=CONTENT_TYPE_LATEST)
