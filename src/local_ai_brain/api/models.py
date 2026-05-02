import time

from fastapi import APIRouter, HTTPException

from ..config import settings

router = APIRouter()


@router.get("/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": settings.QWEN_MODEL_PATH,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local-ai-brain",
            },
            {
                "id": settings.WHISPER_MODEL_PATH,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local-ai-brain",
            },
            {
                "id": settings.KOKORO_MODEL_PATH,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local-ai-brain",
            },
        ],
    }


@router.get("/models/{model_id:path}")
async def get_model(model_id: str):
    valid_models = [
        settings.QWEN_MODEL_PATH,
        settings.WHISPER_MODEL_PATH,
        settings.KOKORO_MODEL_PATH,
    ]
    if model_id in valid_models:
        return {
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "local-ai-brain",
        }
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
