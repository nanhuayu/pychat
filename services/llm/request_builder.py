from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from models.conversation import Conversation, Message
from models.provider import Provider
from core.prompts.system import PromptManager

from utils.image_encoding import encode_image_file_to_data_url


def select_base_messages(conversation: Conversation) -> List[Message]:
    work_dir = getattr(conversation, "work_dir", ".")
    prompt_manager = PromptManager(work_dir)
    
    # Get effective history (filters condensed/truncated messages)
    messages = prompt_manager.get_effective_history(conversation.messages)
    
    # Apply max_context_messages if set
    # Note: We should ideally preserve the summary if it exists, even if max_ctx cuts it off.
    # For now, we apply simple slicing to the result, which might lose the summary if the window is too small.
    # A better approach would be to slice only the messages *after* the summary.
    settings = conversation.settings or {}
    max_ctx = settings.get("max_context_messages")
    if isinstance(max_ctx, int) and max_ctx > 0:
        if len(messages) > max_ctx:
             # Ensure we keep the system prompt if it's first
            if messages and messages[0].role == "system":
                # System prompt + last (max_ctx-1) messages
                return [messages[0]] + messages[-(max_ctx-1):]
            else:
                return messages[-max_ctx:]
                
    return messages


def build_api_messages(messages: List[Message], provider: Provider) -> List[Dict[str, Any]]:
    api_messages: List[Dict[str, Any]] = []

    for msg in messages:
        if msg.role == "tool":
            # message for tool result
            # Use summary if available
            content = msg.summary if msg.summary else msg.content
            
            api_messages.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": content
            })
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

        # Add tool_calls if present (assistant role)
        if msg.tool_calls:
            # Create a clean copy of tool_calls for the API (exclude 'result' field)
            clean_tool_calls = []
            for tc in msg.tool_calls:
                clean_tc = {k: v for k, v in tc.items() if k in ('id', 'type', 'function')}
                clean_tool_calls.append(clean_tc)
            
            message_payload["tool_calls"] = clean_tool_calls
            if not message_payload["content"]:
                message_payload["content"] = None

        # Add reasoning_content if present (required by DeepSeek R1 and similar models)
        if msg.role == "assistant" and msg.thinking:
            # Check metadata for original key, default to standard 'reasoning_content'
            key = msg.metadata.get("thinking_key") or "reasoning_content"
            message_payload[key] = msg.thinking
        
        api_messages.append(message_payload)

        # Expand tool results into separate messages
        if msg.tool_calls:
            for tc in msg.tool_calls:
                if 'result' in tc:
                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get('id'),
                        "content": tc.get('result')
                    })

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
    
    # Use PromptManager to generate the system prompt
    work_dir = getattr(conversation, "work_dir", ".")
    prompt_manager = PromptManager(work_dir)
    
    # Generate structured system prompt
    system_prompt_content = prompt_manager.get_system_prompt(conversation, tools or [], provider)
    
    # Inject into api_messages
    # 1. Find existing system message (from effective history)
    system_msg_index = -1
    for i, msg in enumerate(api_messages):
        if msg.get("role") == "system":
            system_msg_index = i
            break
            
    if system_msg_index >= 0:
        # Update existing system message
        api_messages[system_msg_index]["content"] = system_prompt_content
    else:
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
