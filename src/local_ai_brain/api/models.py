import time

from fastapi import APIRouter, HTTPException

from ..config import settings

router = APIRouter()


def get_valid_models():
    return [
        settings.QWEN_MODEL_PATH,
        settings.WHISPER_MODEL_PATH,
        settings.KOKORO_MODEL_PATH,
    ]


@router.get("/models")
async def list_models():
    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": created,
                "owned_by": "local-ai-brain",
            }
            for model_id in get_valid_models()
        ],
    }


@router.get("/models/{model_id:path}")
async def get_model(model_id: str):
    if model_id in get_valid_models():
        return {
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "local-ai-brain",
        }
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
