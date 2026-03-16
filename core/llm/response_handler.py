"""Response parsing for LLM API calls.

Extracts non-streaming and streaming response handling from
``LLMClient.send_message`` so that ``client.py`` stays focused
on orchestration.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

import httpx

from models.conversation import Message
from core.llm.thinking_parser import ThinkingStreamParser
from core.llm.http_utils import (
    pretty_json,
    read_response_bytes,
    format_http_error,
    parse_json_safely,
    iter_sse_data_lines,
    parse_sse_json,
)
from core.llm.token_utils import estimate_tokens

logger = logging.getLogger(__name__)

# Fields that may contain thinking / reasoning content across providers
THINKING_KEYS = [
    "reasoning_content", "thinking", "reasoning",
    "thinking_content", "thoughts", "thought",
]


def parse_non_stream_response(
    resp: httpx.Response,
    *,
    thinking_parser: ThinkingStreamParser,
    enable_thinking: bool,
    on_token: Optional[Callable[[str], None]],
    start_time: float,
) -> Message:
    """Parse a non-streaming (``stream=false``) HTTP response into a ``Message``."""
    response_content = ""
    thinking_content = ""
    tokens_used = 0
    response_tool_calls: Optional[List[Dict[str, Any]]] = None
    detected_thinking_key = "reasoning_content"

    if resp.status_code >= 400:
        payload = None
        try:
            payload = resp.json()
        except Exception:
            payload = None
        text = ""
        try:
            text = (resp.text or "").strip()
        except Exception:
            text = ""
        response_content = format_http_error(resp.status_code, payload, text)
    else:
        payload = resp.json()
        choices = payload.get("choices", []) if isinstance(payload, dict) else []
        if choices:
            msg = choices[0].get("message", {}) or {}
            if isinstance(msg, dict):
                tcs = msg.get("tool_calls")
                if isinstance(tcs, list) and tcs:
                    response_tool_calls = tcs
            content = msg.get("content", "") or ""
            visible, embedded_thinking = thinking_parser.feed(content)
            response_content += visible

            thinking = ""
            for key in THINKING_KEYS:
                val = msg.get(key)
                if val:
                    thinking = val
                    detected_thinking_key = key
                    break

            if enable_thinking:
                if embedded_thinking:
                    thinking_content += embedded_thinking
                if thinking:
                    thinking_content += thinking
        else:
            response_content = pretty_json(payload)

    if on_token and response_content:
        on_token(response_content)

    response_time_ms = int((time.time() - start_time) * 1000)
    if tokens_used == 0 and response_content:
        tokens_used = estimate_tokens(response_content)

    msg = Message(
        role="assistant",
        content=response_content,
        thinking=thinking_content if thinking_content else None,
        tool_calls=response_tool_calls if response_tool_calls else None,
        tokens=tokens_used,
        response_time_ms=response_time_ms,
    )
    msg.metadata["thinking_key"] = detected_thinking_key
    return msg


async def parse_stream_response(
    response: httpx.Response,
    *,
    thinking_parser: ThinkingStreamParser,
    enable_thinking: bool,
    on_token: Optional[Callable[[str], None]],
    on_thinking: Optional[Callable[[str], None]],
    cancel_event,
    log_fp,
    start_time: float,
) -> Message:
    """Consume an SSE stream and return the final ``Message``."""
    response_content = ""
    thinking_content = ""
    tokens_used = 0
    response_tool_calls: Optional[List[Dict[str, Any]]] = None
    detected_thinking_key = "reasoning_content"

    # HTTP error (non-2xx with streaming client)
    if response.status_code >= 400:
        raw = await read_response_bytes(response)
        text = ""
        payload = None
        if raw:
            try:
                text = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                text = ""
            payload = parse_json_safely(text)

        response_content = format_http_error(response.status_code, payload, text)
        if on_token:
            on_token(response_content)

        response_time_ms = int((time.time() - start_time) * 1000)
        if tokens_used == 0 and response_content:
            tokens_used = estimate_tokens(response_content)
        return Message(
            role="assistant",
            content=response_content,
            thinking=None,
            tokens=tokens_used,
            response_time_ms=response_time_ms,
        )

    # Normal SSE stream
    tool_calls_buffer: List[dict] = []

    async for data in iter_sse_data_lines(response, cancel_event=cancel_event, log_fp=log_fp):
        try:
            chunk_data = parse_sse_json(data)
        except json.JSONDecodeError:
            if log_fp:
                try:
                    log_fp.write("[JSONDecodeError]\n")
                    log_fp.flush()
                except Exception as exc:
                    logger.debug("Failed to write JSON decode marker to stream log: %s", exc)
            continue

        if isinstance(chunk_data, dict) and chunk_data.get("error") is not None:
            response_content = "接口返回错误（stream）：\n" + pretty_json(chunk_data.get("error"))
            if on_token:
                on_token(response_content)
            break

        choices = chunk_data.get("choices", []) if isinstance(chunk_data, dict) else []
        if choices:
            delta = choices[0].get("delta", {}) or {}

            # Accumulate tool calls
            chunk_tool_calls = delta.get("tool_calls")
            if chunk_tool_calls:
                for tc in chunk_tool_calls:
                    index = tc.get("index", 0)
                    while len(tool_calls_buffer) <= index:
                        tool_calls_buffer.append({
                            "id": "", "type": "function",
                            "function": {"name": "", "arguments": ""},
                        })
                    tcb = tool_calls_buffer[index]
                    if tc.get("id"):
                        tcb["id"] = tc["id"]
                    if tc.get("type"):
                        tcb["type"] = tc["type"]
                    func = tc.get("function", {})
                    if func.get("name"):
                        tcb["function"]["name"] += func["name"]
                    if func.get("arguments"):
                        tcb["function"]["arguments"] += func["arguments"]

            # Content tokens
            content = delta.get("content", "") or ""
            if content:
                visible, embedded_thinking = thinking_parser.feed(content)
                if visible:
                    response_content += visible
                    if on_token:
                        on_token(visible)
                if enable_thinking and embedded_thinking:
                    thinking_content += embedded_thinking
                    if on_thinking:
                        on_thinking(embedded_thinking)

            # Thinking fields
            thinking = ""
            for key in THINKING_KEYS:
                val = delta.get(key)
                if val:
                    thinking = val
                    detected_thinking_key = key
                    break
            if enable_thinking and thinking:
                thinking_content += thinking
                if on_thinking:
                    on_thinking(thinking)

    # Stream finished
    if log_fp:
        try:
            log_fp.write("\n===== END STREAM =====\n")
            log_fp.close()
        except Exception as exc:
            logger.debug("Failed to finalize stream log file: %s", exc)

    # Finalize tool calls
    if tool_calls_buffer:
        response_tool_calls = [
            tcb for tcb in tool_calls_buffer
            if tcb.get("function", {}).get("name")
        ]

    response_time_ms = int((time.time() - start_time) * 1000)
    if tokens_used == 0:
        tokens_used = estimate_tokens(response_content)

    msg = Message(
        role="assistant",
        content=response_content,
        thinking=thinking_content if thinking_content else None,
        tool_calls=response_tool_calls if response_tool_calls else None,
        tokens=tokens_used,
        response_time_ms=response_time_ms,
    )
    msg.metadata["thinking_key"] = detected_thinking_key
    return msg
