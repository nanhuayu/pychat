"""LLM Client — orchestrates request building, HTTP transport, and response parsing.

Delegates response parsing to ``core.llm.response_handler``.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Optional, Callable
import threading

import httpx

from models.provider import Provider
from models.conversation import Message, Conversation

from core.llm.thinking_parser import ThinkingStreamParser
from core.llm.request_builder import select_base_messages, build_api_messages, build_request_body
from core.config import load_app_config, AppConfig
from core.llm.response_handler import parse_non_stream_response, parse_stream_response


class LLMClient:
    """Handles chat interactions with LLM providers."""

    def __init__(self, timeout: float = 120.0, mcp_manager=None):
        self.timeout = float(timeout)
        if mcp_manager is not None:
            self.mcp_manager = mcp_manager
        else:
            from core.tools.manager import McpManager
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
        prepared_messages: Optional[list[Message]] = None,
        prepared_tools: Optional[list[dict]] = None,
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

        try:
            try:
                app_config = load_app_config()
            except Exception:
                app_config = AppConfig()

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

            if prepared_tools is not None:
                tools = prepared_tools
            else:
                tools = await self.mcp_manager.get_all_tools(
                    include_search=enable_search,
                    include_mcp=enable_mcp,
                    prepared_queries=[prepared_query] if prepared_query else None,
                )

            if prepared_messages is not None:
                base_messages = prepared_messages
            else:
                base_messages = select_base_messages(conversation, app_config=app_config)
            api_messages = build_api_messages(base_messages, provider)
            request_body = build_request_body(provider, conversation, api_messages, tools=tools, app_config=app_config)

            if True or debug_log_path:
                try:
                    open(f"debug_request_{int(time.time())}.json", "w", encoding="utf-8").write(
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
                    msg = parse_non_stream_response(
                        resp,
                        thinking_parser=thinking_parser,
                        enable_thinking=enable_thinking,
                        on_token=on_token,
                        start_time=start_time,
                    )
                    self._attach_metadata(msg, provider, request_body, conversation)
                    return msg

                # ===== Streaming mode =====
                async with client.stream(
                    "POST",
                    provider.get_chat_endpoint(),
                    headers=provider.get_headers(),
                    json=request_body,
                ) as response:
                    msg = await parse_stream_response(
                        response,
                        thinking_parser=thinking_parser,
                        enable_thinking=enable_thinking,
                        on_token=on_token,
                        on_thinking=on_thinking,
                        cancel_event=cancel_event,
                        log_fp=log_fp,
                        start_time=start_time,
                    )
                    self._attach_metadata(msg, provider, request_body, conversation)
                    return msg

        except Exception as e:
            return Message(
                role="assistant",
                content=f"Error sending message: {str(e)}",
                tokens=0,
                response_time_ms=0,
            )

    @staticmethod
    def _attach_metadata(
        msg: Message,
        provider: Provider,
        request_body: dict,
        conversation: Conversation,
    ) -> None:
        """Attach provider / model metadata to the response message."""
        try:
            msg.metadata.update({
                "provider_id": getattr(provider, "id", ""),
                "provider_name": getattr(provider, "name", ""),
                "model": request_body.get("model")
                if isinstance(request_body, dict)
                else (conversation.model or provider.default_model),
                "thinking_key": msg.metadata.get("thinking_key", "reasoning_content"),
            })
        except Exception:
            pass
