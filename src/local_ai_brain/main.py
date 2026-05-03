import contextlib
import logging
import os
import secrets
import sys

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import settings
from .middleware import MemoryGuardMiddleware, MetricsMiddleware


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        try:
            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
        except ValueError:
            # Call stack is too shallow
            depth = 0

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


logger.remove()


def configure_logging(testing: bool = False):
    if not testing:
        log_path = os.path.expanduser(
            os.getenv("LOCAL_AI_BRAIN_LOG_PATH", "~/Library/Logs/local-ai-brain.log")
        )
        log_directory = os.path.dirname(log_path)
        if log_directory:
            os.makedirs(log_directory, exist_ok=True)
        logger.add(
            log_path,
            level="INFO",
            rotation="10 MB",
            retention="14 days",
            compression="gz",
        )


configure_logging(settings.TESTING)
logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)

for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    logging_logger = logging.getLogger(logger_name)
    logging_logger.handlers = []
    logging_logger.propagate = True

security = HTTPBearer()


def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security)):
    if not secrets.compare_digest(credentials.credentials, settings.LOCAL_API_KEY):
        logger.warning("Unauthorized API access attempt.")
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return credentials.credentials


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=300.0)
    yield
    await app.state.client.aclose()


app = FastAPI(lifespan=lifespan, title="Local AI Brain Proxy")

# Add Middlewares
app.add_middleware(MemoryGuardMiddleware)
app.add_middleware(MetricsMiddleware)

VLLM_URL = os.environ.get("VLLM_URL", "http://127.0.0.1:8001")
STT_URL = os.environ.get("STT_URL", "http://127.0.0.1:8002")
TTS_URL = os.environ.get("TTS_URL", "http://127.0.0.1:8003")


async def proxy_request(request: Request, base_url: str):
    path = request.url.path
    query = request.url.query
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"

    headers = dict(request.headers)
    headers.pop("host", None)

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
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()

        resp_headers = dict(response.headers)
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
    dependencies=[Depends(verify_api_key)],
)
async def proxy_vllm_chat(request: Request, path: str):
    return await proxy_request(request, VLLM_URL)


@app.api_route(
    "/v1/models",
    methods=["GET"],
    dependencies=[Depends(verify_api_key)],
)
async def list_models(request: Request):
    try:
        client = request.app.state.client
        vllm_resp = await client.get(f"{VLLM_URL}/v1/models")
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
                "created": 0,
                "owned_by": "local-ai-brain",
            },
            {
                "id": settings.KOKORO_MODEL_PATH,
                "object": "model",
                "created": 0,
                "owned_by": "local-ai-brain",
            },
        ]
    )
    return data


@app.api_route(
    "/v1/models/{model_id:path}",
    methods=["GET"],
    dependencies=[Depends(verify_api_key)],
)
async def get_model(request: Request, model_id: str):
    if model_id in (settings.WHISPER_MODEL_PATH, settings.KOKORO_MODEL_PATH):
        return {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "local-ai-brain",
        }
    return await proxy_request(request, VLLM_URL)


@app.api_route("/v1/audio/transcriptions", methods=["POST"], dependencies=[Depends(verify_api_key)])
async def proxy_stt(request: Request):
    return await proxy_request(request, STT_URL)


@app.api_route("/v1/audio/speech", methods=["POST"], dependencies=[Depends(verify_api_key)])
async def proxy_tts(request: Request):
    return await proxy_request(request, TTS_URL)


@app.get("/health", tags=["System"], dependencies=[Depends(verify_api_key)])
async def health_check():
    return {"status": "ok", "proxy": "active"}


@app.get("/metrics", tags=["System"], dependencies=[Depends(verify_api_key)])
async def get_metrics(request: Request):
    # Expose Prometheus metrics from OpenTelemetry custom registry
    from .metrics import OTEL_REGISTRY

    proxy_metrics = generate_latest(OTEL_REGISTRY)
    combined_metrics = proxy_metrics

    client = request.app.state.client
    for name, url in [("vLLM", VLLM_URL), ("STT", STT_URL), ("TTS", TTS_URL)]:
        try:
            resp = await client.get(f"{url}/metrics", timeout=2.0)
            if resp.status_code == 200:
                combined_metrics += b"\n" + resp.content
        except Exception as e:
            logger.warning(f"Failed to fetch metrics from {name} at {url}: {e}")

    return Response(combined_metrics, media_type=CONTENT_TYPE_LATEST)
