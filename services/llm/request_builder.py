from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.conversation import Conversation, Message
from models.provider import Provider

from utils.image_encoding import encode_image_file_to_data_url


def select_base_messages(conversation: Conversation) -> List[Message]:
    settings = conversation.settings or {}
    max_ctx = settings.get("max_context_messages")
    if isinstance(max_ctx, int) and max_ctx > 0:
        return conversation.messages[-max_ctx:]
    return conversation.messages


def build_api_messages(messages: List[Message], provider: Provider) -> List[Dict[str, Any]]:
    api_messages: List[Dict[str, Any]] = []

    for msg in messages:
        if msg.role == "tool":
            # message for tool result
            api_messages.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content
            })
            continue

        if msg.images and provider.supports_vision:
            content: list[dict[str, Any]] = []

            if msg.content:
                content.append({"type": "text", "text": msg.content})

            for image in msg.images:
                if not isinstance(image, str) or not image:
                    continue

                if image.startswith("data:") or image.startswith(("http://", "https://")):
                    image_url = image
                else:
                    image_url = encode_image_file_to_data_url(image) or ""

                if image_url:
                    content.append({"type": "image_url", "image_url": {"url": image_url}})

            message_payload = {"role": msg.role, "content": content}
        else:
            message_payload = {"role": msg.role, "content": msg.content}

        # Add tool_calls if present (assistant role)
        if msg.tool_calls:
            message_payload["tool_calls"] = msg.tool_calls
            if not message_payload["content"]:
                message_payload["content"] = None

        # Add reasoning_content if present (required by DeepSeek R1 and similar models)
        if msg.role == "assistant" and msg.thinking:
            # Check metadata for original key, default to standard 'reasoning_content'
            key = msg.metadata.get("thinking_key") or "reasoning_content"
            message_payload[key] = msg.thinking
        
        api_messages.append(message_payload)

    return api_messages


def build_request_body(provider: Provider, conversation: Conversation, api_messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    settings = conversation.settings or {}


    stream_enabled = settings.get("stream", True)
    temperature = settings.get("temperature", 0.7)
    top_p = settings.get("top_p")
    max_tokens = settings.get("max_tokens", 0)

    try:
        stream_enabled = bool(stream_enabled)
    except Exception:
        stream_enabled = True

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

    # Optional conversation system prompt
    system_prompt = settings.get("system_prompt")
    if isinstance(system_prompt, str) and system_prompt.strip():
        # Avoid duplication if system already exists.
        if not any(m.get("role") == "system" for m in api_messages if isinstance(m, dict)):
            body["messages"] = [{"role": "system", "content": system_prompt.strip()}] + body["messages"]

    return body
