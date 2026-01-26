"""Chat service facade.

This module keeps the public `ChatService` entry-point stable for the UI layer,
but pushes the real work into small focused modules under `services/llm/`.

Why
- The old ChatService was a monolith (request building + IO + parsing + logging + token stats).
- Splitting improves readability and makes future provider/protocol changes localized.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Optional, Callable, List, Any, Dict
import threading

import httpx

from models.provider import Provider
from models.conversation import Message, Conversation

from services.llm.thinking_parser import ThinkingStreamParser
from services.llm.request_builder import select_base_messages, build_api_messages, build_request_body
from services.llm.http_utils import (
    pretty_json,
    read_response_bytes,
    format_http_error,
    parse_json_safely,
    iter_sse_data_lines,
    parse_sse_json,
)


def _estimate_tokens(text: str) -> int:
    """Very rough token estimator (for UI stats only)."""
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    other_chars = len(text or "") - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


from services.mcp_manager import McpManager

class ChatService:
    """Handles chat interactions with LLM providers."""

    def __init__(self, timeout: float = 120.0):
        self.timeout = float(timeout)
        self.mcp_manager = McpManager()

    async def send_message(
        self,
        provider: Provider,
        conversation: Conversation,
        on_token: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        enable_thinking: bool = True,
        enable_search: bool = False,
        enable_mcp: bool = False,
        debug_log_path: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Message:
        start_time = time.time()

        thinking_parser = ThinkingStreamParser()
        log_fp = None
        if debug_log_path:
            try:
                log_fp = open(debug_log_path, "a", encoding="utf-8")
                log_fp.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} START =====\n")
                log_fp.flush()
            except Exception:
                log_fp = None

        request_body: dict = {}
        response_content = ""
        thinking_content = ""
        tokens_used = 0
        response_tool_calls: Optional[List[Dict[str, Any]]] = None
        # Default to standard field, but track actual source for accurate playback
        detected_thinking_key: str = "reasoning_content"
        THINKING_KEYS = ["reasoning_content", "thinking", "reasoning", "thinking_content", "thoughts", "thought"]

        try:
            # Gather tools if configured
            prepared_query = ""
            try:
                for m in reversed(getattr(conversation, "messages", []) or []):
                    if getattr(m, "role", "") == "user":
                        prepared_query = (getattr(m, "content", "") or "").strip()
                        if prepared_query:
                            break
            except Exception:
                prepared_query = ""

            tools = await self.mcp_manager.get_all_tools(
                include_search=enable_search,
                include_mcp=enable_mcp,
                prepared_queries=[prepared_query] if prepared_query else None,
            )
            
            base_messages = select_base_messages(conversation)
            api_messages = build_api_messages(base_messages, provider)
            request_body = build_request_body(provider, conversation, api_messages, tools=tools)

            if debug_log_path:
                try:
                    open("debug_request.json", "w", encoding="utf-8").write(
                        json.dumps(request_body, ensure_ascii=False, indent=2)
                    )
                except Exception:
                    pass

            timeout_config = httpx.Timeout(self.timeout, connect=30.0)
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                # ===== Non-stream mode =====
                if not request_body.get("stream", True):
                    resp = await client.post(
                        provider.get_chat_endpoint(),
                        headers=provider.get_headers(),
                        json=request_body,
                    )

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

                    end_time = time.time()
                    response_time_ms = int((end_time - start_time) * 1000)
                    if tokens_used == 0 and response_content:
                        tokens_used = _estimate_tokens(response_content)

                    msg = Message(
                        role="assistant",
                        content=response_content,
                        thinking=thinking_content if thinking_content else None,
                        tool_calls=response_tool_calls if response_tool_calls else None,
                        tokens=tokens_used,
                        response_time_ms=response_time_ms,
                    )
                    try:
                        msg.metadata.update(
                            {
                                "provider_id": getattr(provider, "id", ""),
                                "provider_name": getattr(provider, "name", ""),
                                "model": request_body.get("model")
                                if isinstance(request_body, dict)
                                else (conversation.model or provider.default_model),
                                "thinking_key": detected_thinking_key,
                            }
                        )
                    except Exception:
                        pass
                    return msg

                # ===== Streaming mode =====
                async with client.stream(
                    "POST",
                    provider.get_chat_endpoint(),
                    headers=provider.get_headers(),
                    json=request_body,
                ) as response:
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

                        end_time = time.time()
                        response_time_ms = int((end_time - start_time) * 1000)
                        if tokens_used == 0 and response_content:
                            tokens_used = _estimate_tokens(response_content)
                        return Message(
                            role="assistant",
                            content=response_content,
                            thinking=None,
                            tokens=tokens_used,
                            response_time_ms=response_time_ms,
                        )

                    # State for accumulating tool calls
                    tool_calls_buffer: List[dict] = []
                    
                    async for data in iter_sse_data_lines(response, cancel_event=cancel_event, log_fp=log_fp):
                        try:
                            chunk_data = parse_sse_json(data)
                        except json.JSONDecodeError:
                            if log_fp:
                                try:
                                    log_fp.write("[JSONDecodeError]\n")
                                    log_fp.flush()
                                except Exception:
                                    pass
                            continue

                        if isinstance(chunk_data, dict) and chunk_data.get("error") is not None:
                            response_content = "接口返回错误（stream）：\n" + pretty_json(chunk_data.get("error"))
                            if on_token:
                                on_token(response_content)
                            break

                        choices = chunk_data.get("choices", []) if isinstance(chunk_data, dict) else []
                        if choices:
                            delta = choices[0].get("delta", {}) or {}
                            
                            # Handle tool_calls
                            chunk_tool_calls = delta.get("tool_calls")
                            if chunk_tool_calls:
                                for tc in chunk_tool_calls:
                                    index = tc.get("index", 0)
                                    # Ensure buffer size
                                    while len(tool_calls_buffer) <= index:
                                        tool_calls_buffer.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                                    
                                    tcb = tool_calls_buffer[index]
                                    if tc.get("id"): tcb["id"] = tc["id"]
                                    if tc.get("type"): tcb["type"] = tc["type"]
                                    
                                    func = tc.get("function", {})
                                    if func.get("name"): tcb["function"]["name"] += func["name"]
                                    if func.get("arguments"): tcb["function"]["arguments"] += func["arguments"]
                                    
                                    # We don't stream tool calls to UI generally? Or maybe just simple text notification
                                    # TODO: Callback for tool status? 
                                    
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

                        usage = chunk_data.get("usage", {}) if isinstance(chunk_data, dict) else {}
                        if isinstance(usage, dict) and usage:
                            try:
                                tokens_used = int(usage.get("total_tokens", 0) or 0)
                            except Exception:
                                pass

        except httpx.ConnectError as e:
            response_content = f"连接失败: 无法连接到服务器 ({str(e)[:100]})"
            if on_token:
                on_token(response_content)

        except httpx.TimeoutException:
            response_content = "请求超时: 服务器响应时间过长"
            if on_token:
                on_token(response_content)

        except httpx.HTTPStatusError as e:
            status_code = 0
            try:
                status_code = int(getattr(e.response, "status_code", 0) or 0)
            except Exception:
                status_code = 0

            raw = await read_response_bytes(e.response)
            text = ""
            payload = None
            if raw:
                try:
                    text = raw.decode("utf-8", errors="replace").strip()
                except Exception:
                    text = ""
                payload = parse_json_safely(text)

            response_content = format_http_error(status_code or 0, payload, text)
            if on_token:
                on_token(response_content)

        except Exception as e:
            response_content = f"错误: {str(e)}"
            if on_token:
                on_token(response_content)

        finally:
            if log_fp:
                try:
                    log_fp.write(f"===== {datetime.now().isoformat(timespec='seconds')} END =====\n")
                    log_fp.close()
                except Exception:
                    pass

        end_time = time.time()
        response_time_ms = int((end_time - start_time) * 1000)
        
        # Finalize tool calls
        final_tool_calls = [tc for tc in (locals().get("tool_calls_buffer", []) or []) if tc.get("id")]
        
        if tokens_used == 0 and response_content:
            tokens_used = _estimate_tokens(response_content)

        response_message = Message(
            role="assistant",
            content=response_content,
            thinking=thinking_content if thinking_content else None,
            tool_calls=final_tool_calls if final_tool_calls else None,
            tokens=tokens_used,
            response_time_ms=response_time_ms,
        )

        try:
            response_message.metadata.update(
                {
                    "provider_id": getattr(provider, "id", ""),
                    "provider_name": getattr(provider, "name", ""),
                    "thinking_key": detected_thinking_key,
                    "model": request_body.get("model")
                    if isinstance(request_body, dict)
                    else (conversation.model or provider.default_model),
                }
            )
        except Exception:
            pass

        return response_message
