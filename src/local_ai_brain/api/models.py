import time

from fastapi import APIRouter, HTTPException

from ..config import settings

router = APIRouter()


def get_valid_models():
    created_time = int(time.time())
    max_tokens = settings.MAX_CONTEXT_TOKENS
    return [
        {
            "id": settings.QWEN_MODEL_PATH,
            "object": "model",
            "created": created_time,
            "owned_by": "local-ai-brain",
            "max_model_len": max_tokens,
            "context_window": max_tokens,
            "max_position_embeddings": max_tokens,
        },
        {
            "id": settings.WHISPER_MODEL_PATH,
            "object": "model",
            "created": created_time,
            "owned_by": "local-ai-brain",
        },
        {
            "id": settings.KOKORO_MODEL_PATH,
            "object": "model",
            "created": created_time,
            "owned_by": "local-ai-brain",
        },
    ]


@router.get("/models")
async def list_models():
    return {
        "object": "list",
        "data": get_valid_models(),
    }


@router.get("/models/{model_id:path}")
async def get_model(model_id: str):
    models = get_valid_models()
    # Accept the canonical ID or any configured aliases
    accepted_ids = {settings.QWEN_MODEL_PATH} | set(settings.QWEN_MODEL_ALIASES)
    if model_id in accepted_ids:
        # Always return the canonical Qwen model entry
        for m in models:
            if m["id"] == settings.QWEN_MODEL_PATH:
                return m
    for m in models:
        if m["id"] == model_id:
            return m
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
