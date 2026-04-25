import contextlib
import logging
import sys

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    logging_logger = logging.getLogger(logger_name)
    logging_logger.handlers = []
    logging_logger.propagate = True
from huggingface_hub import hf_hub_download
from huggingface_hub.utils import disable_progress_bars
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .api.audio import router as audio_router
from .api.chat import router as chat_router
from .config import settings
from .middleware import MemoryGuardMiddleware

disable_progress_bars()
import mlx_whisper
from kokoro_onnx import Kokoro
from vllm_mlx.engine.batched import BatchedEngine

security = HTTPBearer()


def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials != settings.LOCAL_API_KEY:
        logger.warning("Unauthorized API access attempt.")
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return credentials.credentials


from .metrics import update_memory_metrics


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Local AI Brain models...")

    try:
        logger.info(
            f"Loading LLM {settings.QWEN_MODEL_PATH}. If missing from cache, "
            "it will be redownloaded automatically..."
        )
        app.state.llm_engine = BatchedEngine(model_name=settings.QWEN_MODEL_PATH)
        await app.state.llm_engine.start()

        logger.info(f"Loading Whisper STT {settings.WHISPER_MODEL_PATH}...")
        # mlx_whisper loads dynamically on first call, but we can store a reference
        app.state.stt_model = mlx_whisper

        logger.info("Loading Kokoro ONNX TTS...")
        onnx_path = hf_hub_download(
            repo_id=settings.KOKORO_HF_REPO, filename=settings.KOKORO_ONNX_FILE
        )
        voices_path = hf_hub_download(
            repo_id=settings.KOKORO_HF_REPO, filename=settings.KOKORO_VOICES_FILE
        )
        app.state.tts_model = Kokoro(onnx_path, voices_path)
    except Exception as e:
        logger.error(f"Failed to initialize models: {e}")
        # In production, we might want to fail-fast or retry depending on the issue.
        raise RuntimeError("Model initialization failed")

    yield

    logger.info("Shutting down Local AI Brain models...")
    if hasattr(app.state, "llm_engine") and app.state.llm_engine:
        await app.state.llm_engine.stop()
    app.state.llm_engine = None
    app.state.stt_model = None
    app.state.tts_model = None


from .middleware import MetricsMiddleware

app = FastAPI(lifespan=lifespan, title="Local AI Brain")

# Add Middlewares
app.add_middleware(MetricsMiddleware)
app.add_middleware(MemoryGuardMiddleware)

# Include Routers with global dependencies for authentication
app.include_router(chat_router, prefix="/v1", dependencies=[Depends(verify_api_key)])
app.include_router(audio_router, prefix="/v1", dependencies=[Depends(verify_api_key)])


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "models_loaded": hasattr(app.state, "llm_engine")}


@app.get("/metrics", tags=["System"])
async def get_metrics():
    # Expose Prometheus metrics with updated memory states
    update_memory_metrics()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
