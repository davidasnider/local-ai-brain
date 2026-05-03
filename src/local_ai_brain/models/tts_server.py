import asyncio
import io
import time

import soundfile as sf
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from local_ai_brain.config import settings
from local_ai_brain.metrics import (
    audio_processing_latency_seconds,
    tts_characters_processed_total,
)
from local_ai_brain.schemas import SpeechRequest

app = FastAPI(title="Local AI Brain - TTS Service")

# Initialize TTS model globally
try:
    from huggingface_hub import hf_hub_download
    from kokoro_onnx import Kokoro

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
    tts_model = Kokoro(onnx_path, voices_path)
except Exception as e:
    logger.error(f"Failed to initialize TTS model: {e}")
    if not settings.TESTING:
        raise RuntimeError("TTS Model initialization failed") from e
    tts_model = None


@app.post("/v1/audio/speech")
async def create_speech(request: Request, body: SpeechRequest):
    if body.response_format and body.response_format != "wav":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported response_format: {body.response_format}. This API only supports wav."
            ),
        )
    model_name = getattr(body, "model", None) or settings.KOKORO_MODEL_PATH
    if model_name != settings.KOKORO_MODEL_PATH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported model: {model_name}. "
                f"This API only supports {settings.KOKORO_MODEL_PATH}"
            ),
        )
    logger.info(f"Received speech request for model: {model_name}, voice: {body.voice}")

    input_len = len(body.input)
    if input_len > settings.TTS_MAX_CHARACTERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Input text is too long ({input_len} characters). "
                f"Maximum allowed is {settings.TTS_MAX_CHARACTERS} characters."
            ),
        )

    if tts_model is None:
        raise HTTPException(status_code=503, detail="TTS model is not initialized.")

    # Custom dynamic routing logic
    active_voice = body.voice
    if body.character and body.season:
        logger.info(
            f"Both character ({body.character}) and season ({body.season}) were provided; "
            "season takes precedence over character."
        )

    if body.character:
        logger.info(f"Dynamic routing for character: {body.character}")
        # Map character to voice profile, e.g., "santa" -> "kokoro_santa_profile.pt"
        active_voice = f"character_{body.character}"

    if body.season:
        logger.info(f"Dynamic routing for season: {body.season}")
        # Map season to voice profile
        active_voice = f"season_{body.season}"

    logger.debug(f"Resolved TTS voice profile to: {active_voice}")

    start_time = time.time()
    try:
        # Increment characters processed
        tts_characters_processed_total.add(input_len)

        def run_kokoro():
            # Create audio numpy array
            audio_array, sample_rate = tts_model.create(
                body.input, voice=active_voice, speed=body.speed if body.speed is not None else 1.0
            )
            # Convert to WAV bytes in memory
            wav_io = io.BytesIO()
            sf.write(wav_io, audio_array, sample_rate, format="WAV")
            wav_io.seek(0)
            return wav_io

        wav_io = await asyncio.to_thread(run_kokoro)
        return StreamingResponse(wav_io, media_type="audio/wav")
    except Exception as e:
        logger.error(f"Error during TTS generation: {e}")
        raise HTTPException(status_code=500, detail="TTS generation failed")
    finally:
        audio_processing_latency_seconds.record(time.time() - start_time)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "tts"}


@app.get("/metrics")
async def get_metrics():
    from local_ai_brain.metrics import OTEL_REGISTRY

    return Response(generate_latest(OTEL_REGISTRY), media_type=CONTENT_TYPE_LATEST)
