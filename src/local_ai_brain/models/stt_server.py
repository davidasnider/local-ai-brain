import asyncio
import os
import secrets
import tempfile
import time
from typing import Optional

import soundfile as sf
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Response,
    Security,
    UploadFile,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from local_ai_brain.config import settings
from local_ai_brain.logging import configure_logging
from local_ai_brain.metrics import (
    audio_processing_latency_seconds,
    stt_audio_seconds_transcribed_total,
)
from local_ai_brain.schemas import TranscriptionResponse

# Standardize logging
configure_logging(settings.TESTING)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(HTTPBearer(auto_error=False)),
):
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.LOCAL_API_KEY
    ):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return credentials.credentials


app = FastAPI(
    title="Local AI Brain - STT Service",
    dependencies=[Depends(verify_api_key)],
)

try:
    import mlx_whisper

    stt_model = mlx_whisper
    logger.info(f"Loaded Whisper STT {settings.WHISPER_MODEL_PATH}...")
except Exception as e:
    logger.error(f"Failed to initialize STT model: {e}")
    if not settings.TESTING:
        raise RuntimeError("STT Model initialization failed") from e
    stt_model = None


@app.post("/v1/audio/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
):
    model_name = model or settings.WHISPER_MODEL_PATH
    if model_name != settings.WHISPER_MODEL_PATH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported model: {model_name}. "
                f"This API only supports {settings.WHISPER_MODEL_PATH}"
            ),
        )
    logger.info(f"Received transcription request for model: {model_name}")
    if language:
        logger.info(f"Requested language: {language}")

    if stt_model is None:
        raise HTTPException(status_code=503, detail="STT model is not initialized.")

    start_time = time.time()

    tmp_path = None
    try:
        # Stream the upload directly to a temporary file to avoid memory spikes
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            while content := await file.read(1024 * 1024):  # 1MB chunks
                tmp.write(content)
            tmp.flush()

        # Define a blocking function for whisper
        def run_whisper():
            try:
                info = sf.info(tmp_path)
                if info.samplerate:
                    duration_seconds = info.frames / info.samplerate
                    stt_audio_seconds_transcribed_total.add(duration_seconds)
            except Exception as e:
                logger.warning(f"Could not calculate audio duration: {e}")

            return stt_model.transcribe(tmp_path, path_or_hf_repo=model_name, language=language)

        result = await asyncio.to_thread(run_whisper)
        text = result.get("text", "")
        return TranscriptionResponse(text=text)
    except Exception as e:
        logger.error(f"Error during transcription: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed")
    finally:
        audio_processing_latency_seconds.record(time.time() - start_time)

        def _safe_unlink(path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"Could not remove temporary audio file {path}: {e}")

        if tmp_path is not None:
            # Use create_task to ensure it runs independently in the background
            asyncio.create_task(asyncio.to_thread(_safe_unlink, tmp_path))


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "stt"}


@app.get("/metrics")
async def get_metrics():
    from local_ai_brain.metrics import OTEL_REGISTRY

    return Response(generate_latest(OTEL_REGISTRY), media_type=CONTENT_TYPE_LATEST)
