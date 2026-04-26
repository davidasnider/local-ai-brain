import asyncio
import io
import os
import tempfile
import time
from typing import Optional

import soundfile as sf
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger

from ..config import settings
from ..metrics import (
    audio_processing_latency_seconds,
    stt_audio_seconds_transcribed_total,
    tts_characters_processed_total,
)
from ..schemas import SpeechRequest, TranscriptionResponse

router = APIRouter()


@router.post("/audio/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    request: Request,
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
    stt_model = getattr(request.app.state, "stt_model", None)
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
                    stt_audio_seconds_transcribed_total.inc(duration_seconds)
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
        audio_processing_latency_seconds.observe(time.time() - start_time)

        def _safe_unlink(path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"Could not remove temporary audio file {path}: {e}")

        if tmp_path is not None:
            # Shield the cleanup to ensure it runs even if the request is cancelled
            asyncio.shield(asyncio.to_thread(_safe_unlink, tmp_path))


@router.post("/audio/speech")
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

    tts_model = getattr(request.app.state, "tts_model", None)
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
        tts_characters_processed_total.inc(input_len)

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
        audio_processing_latency_seconds.observe(time.time() - start_time)
