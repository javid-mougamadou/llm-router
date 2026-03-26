"""Anthropic-compatible /v1/messages endpoint."""

import json
import uuid
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from app.auth import resolve_user, log_usage
from app.bedrock import converse_no_stream, converse_stream
from app.config import MODELS

router = APIRouter()


@router.post("/v1/messages")
async def messages(request: Request):
    user = await resolve_user(request)
    body = await request.json()

    model = body.get("model", "")
    if model not in MODELS:
        raise HTTPException(400, f"Unknown model: {model}. Available: {list(MODELS)}")

    messages = body.get("messages", [])
    max_tokens = min(int(body.get("max_tokens", 4096)), 32768)
    temperature = body.get("temperature")
    stream = body.get("stream", False)

    # Prepend system if present at top level
    system_text = body.get("system")
    if system_text:
        if isinstance(system_text, str):
            messages = [{"role": "system", "content": system_text}] + messages
        elif isinstance(system_text, list):
            text = " ".join(b.get("text", "") for b in system_text if b.get("type") == "text")
            messages = [{"role": "system", "content": text}] + messages

    if stream:
        return StreamingResponse(
            _stream_anthropic(user, model, messages, max_tokens, temperature),
            media_type="text/event-stream",
        )
    else:
        return await _no_stream_anthropic(user, model, messages, max_tokens, temperature)


async def _no_stream_anthropic(user, model, messages, max_tokens, temperature):
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
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    })


async def _stream_anthropic(user, model, messages, max_tokens, temperature):
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    input_tokens = 0
    output_tokens = 0

    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant",
            "model": model, "content": [], "stop_reason": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })

    yield _sse("content_block_start", {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    })

    async for event in converse_stream(model, messages, max_tokens, temperature):
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            text = delta.get("text", "")
            if text:
                yield _sse("content_block_delta", {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text},
                })
        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)

    yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": output_tokens},
    })
    yield _sse("message_stop", {"type": "message_stop"})

    await log_usage(user["id"], model, input_tokens, output_tokens)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
