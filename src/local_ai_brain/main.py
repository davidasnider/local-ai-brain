import contextlib
import logging
import os
import secrets
import sys

import mlx_whisper
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from huggingface_hub import hf_hub_download
from huggingface_hub.utils import disable_progress_bars
from kokoro_onnx import Kokoro
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from vllm_mlx.engine.batched import BatchedEngine
from vllm_mlx.scheduler import SchedulerConfig

from .api.audio import router as audio_router
from .api.chat import router as chat_router
from .api.models import router as models_router
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
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    logging_logger = logging.getLogger(logger_name)
    logging_logger.handlers = []
    logging_logger.propagate = True

disable_progress_bars()

security = HTTPBearer()


def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security)):
    if not secrets.compare_digest(credentials.credentials, settings.LOCAL_API_KEY):
        logger.warning("Unauthorized API access attempt.")
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return credentials.credentials


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.TESTING:
        logger.info("TESTING mode: Skipping model initialization.")
        app.state.llm_engine = None
        app.state.stt_model = None
        app.state.tts_model = None
        yield
        return

    logger.info("Initializing Local AI Brain models...")

    try:
        logger.info(
            f"Loading LLM {settings.QWEN_MODEL_PATH}. If missing from cache, "
            "it will be redownloaded automatically..."
        )
        scheduler_config = SchedulerConfig(
            kv_cache_quantization=settings.LLM_KV_CACHE_QUANTIZATION,
            kv_cache_quantization_bits=settings.LLM_KV_CACHE_BITS,
        )
        app.state.llm_engine = BatchedEngine(
            model_name=settings.QWEN_MODEL_PATH,
            scheduler_config=scheduler_config,
        )
        await app.state.llm_engine.start()

        logger.info(f"Loading Whisper STT {settings.WHISPER_MODEL_PATH}...")
        # mlx_whisper loads dynamically on first call, but we can store a reference
        app.state.stt_model = mlx_whisper

        logger.info("Loading Kokoro ONNX TTS...")
        onnx_path = hf_hub_download(
            repo_id=settings.KOKORO_HF_REPO,
            filename=settings.KOKORO_ONNX_FILE,
            token=settings.HF_TOKEN,
        )
        voices_path = hf_hub_download(
            repo_id=settings.KOKORO_HF_REPO,
            filename=settings.KOKORO_VOICES_FILE,
            token=settings.HF_TOKEN,
        )
        app.state.tts_model = Kokoro(onnx_path, voices_path)
    except Exception as e:
        logger.error(f"Failed to initialize models: {e}")
        # In production, we might want to fail-fast or retry depending on the issue.
        raise RuntimeError("Model initialization failed") from e

    yield

    logger.info("Shutting down Local AI Brain models...")
    if hasattr(app.state, "llm_engine") and app.state.llm_engine:
        await app.state.llm_engine.stop()
    app.state.llm_engine = None
    app.state.stt_model = None
    app.state.tts_model = None


app = FastAPI(lifespan=lifespan, title="Local AI Brain")

# Add Middlewares
app.add_middleware(MemoryGuardMiddleware)
app.add_middleware(MetricsMiddleware)

# Include Routers with global dependencies for authentication
app.include_router(models_router, prefix="/v1", dependencies=[Depends(verify_api_key)])
app.include_router(chat_router, prefix="/v1", dependencies=[Depends(verify_api_key)])
app.include_router(audio_router, prefix="/v1", dependencies=[Depends(verify_api_key)])


@app.get("/health", tags=["System"], dependencies=[Depends(verify_api_key)])
async def health_check():
    return {"status": "ok", "models_loaded": getattr(app.state, "llm_engine", None) is not None}


@app.get("/metrics", tags=["System"], dependencies=[Depends(verify_api_key)])
async def get_metrics():
    # Expose Prometheus metrics from OpenTelemetry custom registry
    from .metrics import OTEL_REGISTRY

    return Response(generate_latest(OTEL_REGISTRY), media_type=CONTENT_TYPE_LATEST)
