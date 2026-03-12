from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from models.conversation import Conversation, Message
from models.provider import Provider
from core.prompts.system import PromptManager
from core.prompts.history import get_effective_history, apply_context_window
from core.config import AppConfig, load_app_config

from utils.image_encoding import encode_image_file_to_data_url

logger = logging.getLogger(__name__)


def select_base_messages(conversation: Conversation, *, app_config: AppConfig | None = None) -> List[Message]:
    cfg = app_config
    if cfg is None:
        try:
            cfg = load_app_config()
        except Exception:
            cfg = AppConfig()

    keep_last_turns = int(
        getattr(getattr(cfg, "context", None), "compression_policy", None).keep_last_n
        if getattr(getattr(cfg, "context", None), "compression_policy", None)
        else 3
    )
    messages = get_effective_history(conversation.messages, keep_last_turns=keep_last_turns)

    settings = conversation.settings or {}
    max_ctx = settings.get("max_context_messages")
    if isinstance(max_ctx, int) and max_ctx > 0:
        return apply_context_window(messages, max_ctx)

    default_max_ctx = int(getattr(getattr(cfg, "context", None), "default_max_context_messages", 0) or 0)
    if default_max_ctx > 0:
        return apply_context_window(messages, default_max_ctx)
                
    return messages


def build_api_messages(messages: List[Message], provider: Provider) -> List[Dict[str, Any]]:
    api_messages: List[Dict[str, Any]] = []

    # Safety check: warn if no user messages in input
    has_user = any(m.role == "user" for m in messages)
    if not has_user:
        logger.warning("build_api_messages: no user messages found — context may be corrupted")

    tool_result_by_id: Dict[str, str] = {}
    for m in messages:
        if m.role != "tool":
            continue
        if not m.tool_call_id:
            continue
        content = m.summary if m.summary else m.content
        if content is None:
            content = ""
        if m.tool_call_id not in tool_result_by_id:
            tool_result_by_id[m.tool_call_id] = content

    for msg in messages:
        if msg.role == "tool":
            continue

        if msg.images and provider.supports_vision:
            content_list: list[dict[str, Any]] = []
            
            # Use summary if available for text part
            text_content = msg.summary if msg.summary else msg.content
            
            if text_content:
                content_list.append({"type": "text", "text": text_content})

            for image in msg.images:
                if not isinstance(image, str) or not image:
                    continue

                if image.startswith("data:") or image.startswith(("http://", "https://")):
                    image_url = image
                else:
                    image_url = encode_image_file_to_data_url(image) or ""

                if image_url:
                    content_list.append({"type": "image_url", "image_url": {"url": image_url}})

            message_payload = {"role": msg.role, "content": content_list}
        else:
            # Use summary if available
            content = msg.summary if msg.summary else msg.content
            message_payload = {"role": msg.role, "content": content}

        if msg.tool_calls and msg.role == "assistant":
            tool_calls_with_results: List[Dict[str, Any]] = []
            for tc in msg.tool_calls:
                if not isinstance(tc, dict):
                    continue
                tc_id = tc.get("id")
                if not tc_id:
                    continue
                result = tc.get("result")
                if result is None:
                    result = tool_result_by_id.get(tc_id)
                if result is None:
                    continue

                clean_tc = {k: v for k, v in tc.items() if k in ("id", "type", "function")}
                tool_calls_with_results.append(
                    {
                        "clean": clean_tc,
                        "result": result,
                        "id": tc_id,
                    }
                )

            if tool_calls_with_results:
                for i, tc in enumerate(tool_calls_with_results):
                    assistant_payload: Dict[str, Any] = {
                        "role": "assistant",
                        "content": message_payload.get("content") if i == 0 else None,
                        "tool_calls": [tc["clean"]],
                    }

                    if msg.thinking and i == 0:
                        key = msg.metadata.get("thinking_key") or "reasoning_content"
                        assistant_payload[key] = msg.thinking

                    api_messages.append(assistant_payload)
                    api_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": tc["result"],
                        }
                    )
                continue

        if msg.role == "assistant" and msg.thinking:
            key = msg.metadata.get("thinking_key") or "reasoning_content"
            message_payload[key] = msg.thinking

        api_messages.append(message_payload)

    return api_messages


def build_request_body(
    provider: Provider,
    conversation: Conversation,
    api_messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    *,
    app_config: AppConfig | None = None,
) -> Dict[str, Any]:
    settings = conversation.settings or {}


    stream_enabled = settings.get("stream", True)
    temperature = settings.get("temperature", 0.7)
    top_p = settings.get("top_p")
    max_tokens = settings.get("max_tokens", 0)

    try:
        stream_enabled = bool(stream_enabled)
    except Exception:
        stream_enabled = True
    # Respect a pre-assembled system message if the caller already prepared one.
    system_msg_index = -1
    for i, msg in enumerate(api_messages):
        if msg.get("role") == "system":
            system_msg_index = i
            break

    if system_msg_index < 0:
        system_prompt_override = (settings or {}).get("system_prompt_override")
        if isinstance(system_prompt_override, str) and system_prompt_override.strip():
            system_prompt_content = system_prompt_override.strip()
        else:
            work_dir = getattr(conversation, "work_dir", ".")
            prompt_manager = PromptManager(work_dir)
            cfg = app_config
            if cfg is None:
                try:
                    cfg = load_app_config()
                except Exception:
                    cfg = AppConfig()

            system_prompt_content = prompt_manager.get_system_prompt(
                conversation,
                tools or [],
                provider,
                app_config=cfg,
            )

        # Insert new system message at the beginning
        api_messages.insert(0, {
            "role": "system",
            "content": system_prompt_content
        })
    
    body: Dict[str, Any] = {
        "model": conversation.model or provider.default_model,
        "messages": api_messages,
        "temperature": temperature,
        "stream": stream_enabled,
    }

    if max_tokens > 0:
        body["max_tokens"] = max_tokens
    
    if tools:
        body["tools"] = tools
        # OpenAI-compatible default: let the model decide when to call tools.
        body.setdefault("tool_choice", "auto")

    if isinstance(top_p, (int, float)):
        body["top_p"] = float(top_p)

    # Provider-level extras are merged (without overriding core keys).
    extras = getattr(provider, "request_format", None)
    if isinstance(extras, dict) and extras:
        protected = {"model", "messages"}
        for k, v in extras.items():
            if k in protected or k in body:
                continue
            body[k] = v

    return body
