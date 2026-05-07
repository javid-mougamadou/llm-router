"""AWS Bedrock Converse API client (sync + streaming)."""

import logging
import boto3
import asyncio
from botocore.config import Config
from typing import AsyncIterator
from functools import partial
from botocore.exceptions import (
    NoCredentialsError,
    ClientError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)
from fastapi import HTTPException
from app.config import AWS_REGION, AWS_PROFILE, MODELS

log = logging.getLogger(__name__)


def _handle_aws_error(exc: Exception):
    """Convert AWS credential/auth errors to HTTP 502."""
    log.error("AWS Bedrock error: %s", exc)
    # Reset client so next request retries fresh credentials
    global _client
    _client = None
    raise HTTPException(
        502,
        "AWS Bedrock unavailable — check server logs for details",
    )

# Singleton client — reuse session + HTTP connection pool
_client = None


def _get_client():
    global _client
    if _client is None:
        session = boto3.Session(
            profile_name=AWS_PROFILE, region_name=AWS_REGION,
        )
        _client = session.client(
            "bedrock-runtime",
            region_name=AWS_REGION,
            config=Config(read_timeout=300, connect_timeout=10),
        )
    return _client


def _to_converse_messages(messages: list[dict]) -> list[dict]:
    """Convert Anthropic/OpenAI messages to Bedrock Converse format."""
    out = []
    for m in messages:
        role = m["role"]
        if role == "system":
            continue
        content = m.get("content", "")
        if isinstance(content, str):
            out.append({"role": role, "content": [{"text": content}]})
        elif isinstance(content, list):
            blocks = []
            for b in content:
                if isinstance(b, str):
                    blocks.append({"text": b})
                elif b.get("type") == "text":
                    blocks.append({"text": b["text"]})
                elif b.get("type") == "tool_use":
                    blocks.append({"toolUse": {
                        "toolUseId": b["id"],
                        "name": b["name"],
                        "input": b.get("input", {}),
                    }})
                elif b.get("type") == "tool_result":
                    rc_list = b.get("content") or []
                    if isinstance(rc_list, str):
                        rc_list = [{"type": "text", "text": rc_list}]
                    result_content = []
                    for rc in rc_list:
                        if isinstance(rc, str):
                            result_content.append({"text": rc})
                        elif rc.get("type") == "text":
                            result_content.append({"text": rc["text"]})
                    blocks.append({"toolResult": {
                        "toolUseId": b["tool_use_id"],
                        "content": result_content or [{"text": ""}],
                    }})
            out.append({"role": role, "content": blocks})
    return out


def _extract_system(messages: list[dict]) -> list[dict] | None:
    """Extract system messages for Bedrock Converse."""
    parts = []
    for m in messages:
        if m.get("role") == "system":
            c = m.get("content", "")
            if isinstance(c, str):
                parts.append({"text": c})
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, str):
                        parts.append({"text": b})
                    elif b.get("type") == "text":
                        parts.append({"text": b["text"]})
    return parts if parts else None


def _build_kwargs(model, messages, max_tokens, temperature, tools=None, tool_choice=None):
    """Build common kwargs for converse/converse_stream."""
    bedrock_id = MODELS[model]["bedrock_id"]
    conv_msgs = _to_converse_messages(messages)
    system = _extract_system(messages)
    kwargs = {
        "modelId": bedrock_id,
        "messages": conv_msgs,
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["inferenceConfig"]["temperature"] = temperature
    if tools:
        tool_specs = [{"toolSpec": {
            "name": t["name"],
            "description": t.get("description", ""),
            "inputSchema": {"json": t.get("input_schema", {})},
        }} for t in tools]
        tc = {"tools": tool_specs}
        if tool_choice:
            ctype = tool_choice.get("type", "auto")
            if ctype == "auto":
                tc["toolChoice"] = {"auto": {}}
            elif ctype == "any":
                tc["toolChoice"] = {"any": {}}
            elif ctype == "tool":
                tc["toolChoice"] = {"tool": {"name": tool_choice["name"]}}
        kwargs["toolConfig"] = tc
    return kwargs


def converse_no_stream(
    model: str,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float | None = None,
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
) -> dict:
    """Non-streaming Bedrock Converse call. Returns full response."""
    try:
        client = _get_client()
        kwargs = _build_kwargs(model, messages, max_tokens, temperature, tools, tool_choice)
        return client.converse(**kwargs)
    except HTTPException:
        raise
    except (NoCredentialsError, TokenRetrievalError,
            UnauthorizedSSOTokenError) as exc:
        _handle_aws_error(exc)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("ExpiredTokenException",
                    "UnrecognizedClientException",
                    "AccessDeniedException",
                    "InvalidSignatureException"):
            _handle_aws_error(exc)
        raise


async def converse_stream(
    model: str,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float | None = None,
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
) -> AsyncIterator[dict]:
    """Streaming Bedrock ConverseStream. Yields event dicts.

    The initial API call and each iteration over the stream run
    in the thread-pool executor so the event loop is never blocked.
    """
    try:
        client = _get_client()
        kwargs = _build_kwargs(model, messages, max_tokens, temperature, tools, tool_choice)

        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, partial(client.converse_stream, **kwargs),
        )
    except (NoCredentialsError, TokenRetrievalError,
            UnauthorizedSSOTokenError) as exc:
        _handle_aws_error(exc)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("ExpiredTokenException",
                    "UnrecognizedClientException",
                    "AccessDeniedException",
                    "InvalidSignatureException"):
            _handle_aws_error(exc)
        raise

    stream = resp.get("stream")
    if not stream:
        return

    # Wrap the synchronous iterator to avoid blocking the loop
    sentinel = object()
    stream_iter = iter(stream)
    while True:
        try:
            event = await loop.run_in_executor(
                None, next, stream_iter, sentinel,
            )
        except (NoCredentialsError, TokenRetrievalError,
                UnauthorizedSSOTokenError) as exc:
            _handle_aws_error(exc)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("ExpiredTokenException",
                        "UnrecognizedClientException",
                        "AccessDeniedException",
                        "InvalidSignatureException"):
                _handle_aws_error(exc)
            raise
        if event is sentinel:
            break
        yield event
