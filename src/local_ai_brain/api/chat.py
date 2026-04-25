import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from ..config import settings
from ..metrics import (
    llm_active_requests,
    llm_generation_latency_seconds,
    llm_tokens_consumed_total,
    llm_tokens_generated_total,
)
from ..schemas import ChatCompletionRequest

router = APIRouter()


@router.post("/chat/completions")
async def chat_completions(request: Request, body: ChatCompletionRequest):
    model_name = getattr(body, "model", None) or settings.QWEN_MODEL_PATH
    if model_name != settings.QWEN_MODEL_PATH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported model: {model_name}. "
                f"This API only supports {settings.QWEN_MODEL_PATH}"
            ),
        )
    logger.info(f"Received chat completion request for model: {model_name}")

    engine = getattr(request.app.state, "llm_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="LLM engine is not initialized.")

    llm_active_requests.inc()
    start_time = time.time()
    decremented = False
    try:
        messages_dict = [msg.model_dump(exclude_none=True) for msg in body.messages]

        if body.stream:

            async def generate_stream():
                nonlocal decremented
                try:
                    prompt_len = sum(len(m.get("content", "")) for m in messages_dict)
                    llm_tokens_consumed_total.inc(prompt_len // 4 or 1)

                    async for chunk in engine.stream_chat(
                        messages=messages_dict,
                        max_tokens=body.max_tokens or 2048,
                        temperature=body.temperature,
                        top_p=body.top_p,
                    ):
                        llm_tokens_generated_total.inc(1)
                        response_chunk = {
                            "id": f"chatcmpl-{uuid.uuid4()}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk.new_text},
                                    "finish_reason": chunk.finish_reason,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(response_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                finally:
                    if not decremented:
                        llm_active_requests.dec()
                        llm_generation_latency_seconds.observe(time.time() - start_time)
                        decremented = True

            return StreamingResponse(generate_stream(), media_type="text/event-stream")
        else:
            output = await engine.chat(
                messages=messages_dict,
                max_tokens=body.max_tokens or 2048,
                temperature=body.temperature,
                top_p=body.top_p,
            )
            prompt_toks = getattr(output, "prompt_tokens", 0)
            gen_toks = getattr(output, "completion_tokens", 0)
            llm_tokens_consumed_total.inc(prompt_toks)
            llm_tokens_generated_total.inc(gen_toks)

            return {
                "id": f"chatcmpl-{uuid.uuid4()}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": output.text,
                        },
                        "finish_reason": output.finish_reason or "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_toks,
                    "completion_tokens": gen_toks,
                    "total_tokens": prompt_toks + gen_toks,
                },
            }
    except Exception as e:
        logger.error(f"Error during chat completion: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if not body.stream and not decremented:
            llm_active_requests.dec()
            llm_generation_latency_seconds.observe(time.time() - start_time)
            decremented = True
