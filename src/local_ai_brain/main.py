import contextlib
import secrets

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
    yield
    await app.state.client.aclose()


app = FastAPI(
    lifespan=lifespan,
    title="Local AI Brain Gateway",
    dependencies=[Depends(verify_api_key)],
)

# Add Middlewares
app.add_middleware(MetricsMiddleware)


async def proxy_request(request: Request, target_url: str):
    """Proxy the request to a backend service."""
    path = request.url.path
    query = request.url.query
    url = f"{target_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"

    headers = dict(request.headers)
    # Strip hop-by-hop and client auth headers before proxying
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
    ]
    for h in headers_to_strip:
        headers.pop(h, None)

    # Inject internal authentication
    headers["Authorization"] = f"Bearer {settings.LOCAL_API_KEY}"

    client = request.app.state.client
    req = client.build_request(
        method=request.method,
        url=url,
        headers=headers,
        content=request.stream(),
    )

    try:
        response = await client.send(req, stream=True)

        async def stream_generator():
            try:
                # Use aiter_bytes() to ensure httpx handles decompression if the
                # content-encoding header was stripped or modified.
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()

        resp_headers = dict(response.headers)
        # Strip backend-specific hop-by-hop headers from the response
        hop_by_hop_headers = [
            "connection",
            "keep-alive",
            "transfer-encoding",
            "content-length",
            "content-encoding",
        ]
        for h in hop_by_hop_headers:
            resp_headers.pop(h, None)

        return StreamingResponse(
            stream_generator(), status_code=response.status_code, headers=resp_headers
        )
    except httpx.RequestError as e:
        logger.error(f"Proxy error to {url}: {e}")
        raise HTTPException(status_code=502, detail="Bad Gateway")


@app.api_route(
    "/v1/chat/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def proxy_vllm_chat(request: Request, path: str):
    return await proxy_request(request, settings.VLLM_URL)


@app.api_route(
    "/v1/completions",
    methods=["GET", "POST"],
)
async def proxy_vllm_completions(request: Request):
    return await proxy_request(request, settings.VLLM_URL)


@app.get("/v1/models")
async def list_models(request: Request):
    """List available models by merging vLLM models with local ones."""
    try:
        client = request.app.state.client
        # Add internal auth to backend request and use a short timeout
        headers = {"Authorization": f"Bearer {settings.LOCAL_API_KEY}"}
        vllm_resp = await client.get(f"{settings.VLLM_URL}/v1/models", headers=headers, timeout=5.0)
        vllm_resp.raise_for_status()
        data = vllm_resp.json()
    except Exception as e:
        logger.error(f"Failed to fetch models from vLLM: {e}")
        data = {"object": "list", "data": []}

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
    return data


@app.get("/v1/models/{model_id:path}")
async def get_model(model_id: str, request: Request):
    """Get details for a specific model. Fixes 404s from some clients."""
    # Normalize model_id (some clients URL-encode it)
    from urllib.parse import unquote

    model_id = unquote(model_id)

    # Check against our configured models
    is_qwen = model_id == settings.QWEN_MODEL_PATH or model_id in settings.QWEN_MODEL_ALIASES
    is_stt = model_id == settings.WHISPER_MODEL_PATH
    is_tts = model_id == settings.KOKORO_MODEL_PATH

    if is_qwen or is_stt or is_tts:
        resp = {
            "id": settings.QWEN_MODEL_PATH if is_qwen else model_id,
            "object": "model",
            "created": 1700000000,
            "owned_by": "local-ai-brain",
            "type": "llm" if is_qwen else ("stt" if is_stt else "tts"),
        }
        if is_qwen:
            resp.update(
                {
                    "max_model_len": settings.MAX_CONTEXT_TOKENS,
                    "context_window": settings.MAX_CONTEXT_TOKENS,
                    "max_position_embeddings": settings.MAX_CONTEXT_TOKENS,
                }
            )
        return resp

    # Fallback: proxy to vLLM
    return await proxy_request(request, settings.VLLM_URL)


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
        from local_ai_brain import __version__

        version = __version__
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
                # Prefix metrics with service name to avoid collisions
                prefix = f"{name.lower()}_".encode()
                prefixed_content = []
                for line in resp.content.splitlines():
                    if not line.strip():
                        continue
                    if line.startswith(b"#"):
                        # Handle # HELP and # TYPE lines
                        parts = line.split(b" ")
                        if len(parts) > 2:
                            # Prepend prefix to the metric name (3rd field)
                            # Format: # HELP metric_name description
                            # Format: # TYPE metric_name type
                            line = parts[0] + b" " + parts[1] + b" " + prefix + b" ".join(parts[2:])
                    else:
                        # Actual metric line
                        line = prefix + line
                    prefixed_content.append(line)
                combined_metrics += b"\n" + b"\n".join(prefixed_content)
        except Exception as e:
            logger.warning(f"Failed to fetch metrics from {name} at {url}: {e}")

    return Response(combined_metrics, media_type=CONTENT_TYPE_LATEST)
