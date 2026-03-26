"""OpenAI-compatible /v1/chat/completions + /v1/models endpoints."""

import json
import uuid
import time
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from app.auth import resolve_user, log_usage
from app.bedrock import converse_no_stream, converse_stream
from app.config import MODELS

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request):
    await resolve_user(request)
    models = [
        {
            "id": name,
            "object": "model",
            "owned_by": "bedrock",
            "bedrock_id": info["bedrock_id"],
            "input_price": info["input_price"],
            "output_price": info["output_price"],
        }
        for name, info in MODELS.items()
    ]
    return {"object": "list", "data": models}


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    user = await resolve_user(request)
    body = await request.json()

    model = body.get("model", "")
    if model not in MODELS:
        raise HTTPException(400, f"Unknown model: {model}. Available: {list(MODELS)}")

    messages = body.get("messages", [])
    max_tokens = min(int(body.get("max_tokens", 4096)), 32768)
    temperature = body.get("temperature")
    stream = body.get("stream", False)

    if stream:
        return StreamingResponse(
            _stream_openai(user, model, messages, max_tokens, temperature),
            media_type="text/event-stream",
        )
    else:
        return await _no_stream_openai(user, model, messages, max_tokens, temperature)


async def _no_stream_openai(user, model, messages, max_tokens, temperature):
    import asyncio
    from functools import partial
    resp = await asyncio.get_running_loop().run_in_executor(
        None, partial(converse_no_stream, model, messages, max_tokens, temperature)
    )
    output = resp.get("output", {})
    content_blocks = output.get("message", {}).get("content", [])
    usage = resp.get("usage", {})
    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)

    await log_usage(user["id"], model, input_tokens, output_tokens)

    text = "".join(b.get("text", "") for b in content_blocks)
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    })


async def _stream_openai(user, model, messages, max_tokens, temperature):
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    input_tokens = 0
    output_tokens = 0

    yield _sse({
        "id": chat_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    })

    async for event in converse_stream(model, messages, max_tokens, temperature):
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            text = delta.get("text", "")
            if text:
                yield _sse({
                    "id": chat_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                })
        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)

    yield _sse({
        "id": chat_id, "object": "chat.completion.chunk",
        "created": created, "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    })
    yield "data: [DONE]\n\n"

    await log_usage(user["id"], model, input_tokens, output_tokens)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
