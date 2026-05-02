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

# Conservative chars-per-token heuristic for context window safety and metrics
TOKEN_ESTIMATION_FACTOR = 3


@router.post("/chat/completions")
async def chat_completions(request: Request, body: ChatCompletionRequest):
    model_name = getattr(body, "model", None) or settings.QWEN_MODEL_PATH
    # Accept the canonical path plus any configured aliases. Aliases are only
    # valid when they were historically pointing at the current model; if
    # QWEN_MODEL_PATH has been overridden to a different model the legacy IDs
    # should not silently route to it.
    accepted_ids = {settings.QWEN_MODEL_PATH} | set(settings.QWEN_MODEL_ALIASES)
    if model_name not in accepted_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported model: {model_name}. "
                f"This API only supports {settings.QWEN_MODEL_PATH}"
            ),
        )
    # Normalize any alias to the canonical model path so response is consistent
    model_name = settings.QWEN_MODEL_PATH
    logger.info(f"Received chat completion request for model: {model_name}")

    engine = getattr(request.app.state, "llm_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="LLM engine is not initialized.")

    llm_active_requests.add(1)
    start_time = time.time()
    decremented = False
    try:
        messages_dict = [msg.model_dump(exclude_none=True) for msg in body.messages]

        # Calculate prompt length (heuristic)
        prompt_len = 0
        for m in messages_dict:
            content = m.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        prompt_len += len(part["text"])
                    elif isinstance(part, str):
                        prompt_len += len(part)
            elif isinstance(content, str):
                prompt_len += len(content)

        # Determine effective max tokens
        estimated_prompt_tokens = prompt_len // TOKEN_ESTIMATION_FACTOR
        if estimated_prompt_tokens >= settings.MAX_CONTEXT_TOKENS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Prompt is too long (estimated {estimated_prompt_tokens} tokens). "
                    f"Maximum context size is {settings.MAX_CONTEXT_TOKENS} tokens."
                ),
            )

        # Determine effective max tokens, preferring the newer max_completion_tokens
        # but falling back to max_tokens or the system default.
        raw_max = body.max_completion_tokens or body.max_tokens
        requested_max = raw_max if raw_max is not None else settings.DEFAULT_MAX_TOKENS

        # Clamp max tokens to the available context window
        available_window = settings.MAX_CONTEXT_TOKENS - estimated_prompt_tokens
        effective_max_tokens = min(requested_max, available_window)

        # Normalize stop tokens: vllm-mlx expects a list of strings.
        stop_tokens = body.stop
        if isinstance(stop_tokens, str):
            stop_tokens = [stop_tokens]
        elif stop_tokens is None:
            stop_tokens = []

        # Prepare sampling params for engine. These are passed as kwargs to
        # engine.chat or engine.stream_chat, which then populates SamplingParams.
        sampling_kwargs = {
            "max_tokens": effective_max_tokens,
            "temperature": body.temperature,
            "top_p": body.top_p,
            "stop": stop_tokens,
            "presence_penalty": body.presence_penalty,
            "repetition_penalty": body.repetition_penalty,
            "min_p": body.min_p,
            "top_k": body.top_k,
            "seed": body.seed,
            "tools": body.tools,
            "tool_choice": body.tool_choice,
            "response_format": body.response_format,
            "logit_bias": body.logit_bias,
        }

        if body.stream:

            async def generate_stream():
                nonlocal decremented
                try:
                    completion_id = f"chatcmpl-{uuid.uuid4()}"
                    llm_tokens_consumed_total.add(estimated_prompt_tokens)

                    async for chunk in engine.stream_chat(
                        messages=messages_dict,
                        **sampling_kwargs,
                    ):
                        # Heuristic: estimation based on character count
                        llm_tokens_generated_total.add(
                            len(chunk.new_text) // TOKEN_ESTIMATION_FACTOR
                        )
                        response_chunk = {
                            "id": completion_id,
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
                        llm_active_requests.add(-1)
                        llm_generation_latency_seconds.record(time.time() - start_time)
                        decremented = True

            return StreamingResponse(generate_stream(), media_type="text/event-stream")
        else:
            output = await engine.chat(
                messages=messages_dict,
                **sampling_kwargs,
            )
            prompt_toks = getattr(output, "prompt_tokens", 0)
            gen_toks = getattr(output, "completion_tokens", 0)
            llm_tokens_consumed_total.add(prompt_toks)
            llm_tokens_generated_total.add(gen_toks)

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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during chat completion: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if not body.stream and not decremented:
            llm_active_requests.add(-1)
            llm_generation_latency_seconds.record(time.time() - start_time)
            decremented = True
