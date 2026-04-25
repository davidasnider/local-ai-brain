import asyncio
import io
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
            detail=f"Unsupported model: {model_name}. This API only supports {settings.WHISPER_MODEL_PATH}",
        )
    logger.info(f"Received transcription request for model: {model_name}")
    stt_model = getattr(request.app.state, "stt_model", None)
    if stt_model is None:
        raise HTTPException(status_code=503, detail="STT model is not initialized.")

    import time

    start_time = time.time()
    try:
        audio_content = await file.read()

        # Define a blocking function for whisper
        def run_whisper():
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_content)
                tmp.flush()

                # Get audio duration
                try:
                    data, samplerate = sf.read(tmp.name)
                    duration_seconds = len(data) / samplerate
                    stt_audio_seconds_transcribed_total.inc(duration_seconds)
                except Exception as e:
                    logger.warning(f"Could not calculate audio duration: {e}")

                # Run transcription
                result = stt_model.transcribe(tmp.name, path_or_hf_repo=model_name)
            return result

        result = await asyncio.to_thread(run_whisper)
        audio_processing_latency_seconds.observe(time.time() - start_time)
        text = result.get("text", "")
        return TranscriptionResponse(text=text)
    except Exception as e:
        logger.error(f"Error during transcription: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed")


@router.post("/audio/speech")
async def create_speech(request: Request, body: SpeechRequest):
    model_name = getattr(body, "model", None) or settings.KOKORO_MODEL_PATH
    if model_name != settings.KOKORO_MODEL_PATH:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model: {model_name}. This API only supports {settings.KOKORO_MODEL_PATH}",
        )
    logger.info(f"Received speech request for model: {model_name}, voice: {body.voice}")
    tts_model = getattr(request.app.state, "tts_model", None)
    if tts_model is None:
        raise HTTPException(status_code=503, detail="TTS model is not initialized.")

    # Custom dynamic routing logic
    active_voice = body.voice
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
        tts_characters_processed_total.inc(len(body.input))

        def run_kokoro():
            # Create audio numpy array
            audio_array, sample_rate = tts_model.create(
                body.input, voice=active_voice, speed=body.speed or 1.0
            )
            # Convert to WAV bytes in memory
            wav_io = io.BytesIO()
            sf.write(wav_io, audio_array, sample_rate, format="WAV")
            wav_io.seek(0)
            return wav_io.read()

        wav_bytes = await asyncio.to_thread(run_kokoro)
        audio_processing_latency_seconds.observe(time.time() - start_time)
        return StreamingResponse(io.BytesIO(wav_bytes), media_type="audio/wav")
    except Exception as e:
        logger.error(f"Error during TTS generation: {e}")
        raise HTTPException(status_code=500, detail="TTS generation failed")
