"""
Chat service for LLM API interactions - Fixed streaming
"""

import time
import base64
import httpx
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from models.provider import Provider
from models.conversation import Message, Conversation


class _ThinkingStreamParser:
    """Split <think>...</think> (or <analysis>...</analysis>) from normal content.

    Many OpenAI-compatible proxies / open-source models output thinking in-band.
    We extract it into a separate stream so UI can show it as "思考".
    """

    def __init__(self):
        self._buffer = ""
        self._in_think = False

    def feed(self, text: str) -> tuple[str, str]:
        if not text:
            return "", ""

        self._buffer += text
        out_visible: list[str] = []
        out_thinking: list[str] = []

        while self._buffer:
            if self._in_think:
                end_idx = self._buffer.find("</think>")
                alt_end_idx = self._buffer.find("</analysis>")
                if end_idx == -1 or (alt_end_idx != -1 and alt_end_idx < end_idx):
                    end_idx = alt_end_idx

                if end_idx == -1:
                    out_thinking.append(self._buffer)
                    self._buffer = ""
                    break

                out_thinking.append(self._buffer[:end_idx])
                close_len = len("</think>") if self._buffer.startswith("</think>", end_idx) else len("</analysis>")
                self._buffer = self._buffer[end_idx + close_len :]
                self._in_think = False
                continue

            # not in thinking
            start_idx = self._buffer.find("<think>")
            alt_start_idx = self._buffer.find("<analysis>")
            if start_idx == -1 or (alt_start_idx != -1 and alt_start_idx < start_idx):
                start_idx = alt_start_idx

            if start_idx == -1:
                out_visible.append(self._buffer)
                self._buffer = ""
                break

            out_visible.append(self._buffer[:start_idx])
            open_len = len("<think>") if self._buffer.startswith("<think>", start_idx) else len("<analysis>")
            self._buffer = self._buffer[start_idx + open_len :]
            self._in_think = True

        return "".join(out_visible), "".join(out_thinking)


class ChatService:
    """Handles chat interactions with LLM providers"""
    
    def __init__(self):
        self.timeout = 120.0
        self._cancel_requested = False
    
    def cancel_request(self):
        """Cancel the current request"""
        self._cancel_requested = True
    
    async def send_message(
        self,
        provider: Provider,
        conversation: Conversation,
        on_token: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        enable_thinking: bool = True,
        debug_log_path: Optional[str] = None
    ) -> Message:
        """Send a message and get response (with streaming support)"""
        self._cancel_requested = False
        start_time = time.time()

        thinking_parser = _ThinkingStreamParser()
        log_fp = None
        if debug_log_path:
            try:
                log_fp = open(debug_log_path, 'a', encoding='utf-8')
                log_fp.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} START =====\n")
                log_fp.flush()
            except Exception:
                log_fp = None
        
        # Build messages for API
        conv_settings = conversation.settings or {}

        max_ctx = conv_settings.get('max_context_messages')
        if isinstance(max_ctx, int) and max_ctx > 0:
            base_messages = conversation.messages[-max_ctx:]
        else:
            base_messages = conversation.messages

        api_messages = self._build_api_messages(base_messages, provider)

        system_prompt = conv_settings.get('system_prompt')
        if isinstance(system_prompt, str) and system_prompt.strip():
            # Avoid duplicating if conversation already contains system messages.
            if not any(m.get('role') == 'system' for m in api_messages if isinstance(m, dict)):
                api_messages = [{'role': 'system', 'content': system_prompt.strip()}] + api_messages
        
        # Build request body
        # Conversation-level settings with sensible defaults
        stream_enabled = conv_settings.get('stream', True)
        temperature = conv_settings.get('temperature', 0.7)
        top_p = conv_settings.get('top_p')
        max_tokens = conv_settings.get('max_tokens', 65536)

        try:
            stream_enabled = bool(stream_enabled)
        except Exception:
            stream_enabled = True

        request_body = {
            "model": conversation.model or provider.default_model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream_enabled
        }

        if isinstance(top_p, (int, float)):
            request_body["top_p"] = float(top_p)

        def _merge_request_extras(base: Dict[str, Any], extras: Any) -> None:
            """Merge provider extra JSON fields into request body.

            Debug-friendly + safer than a blind update:
            - Only merges dict extras.
            - Does not override core keys by default.
            """

            if not isinstance(extras, dict) or not extras:
                return

            protected_keys = {"model", "messages"}
            skipped: Dict[str, Any] = {}
            merged_keys: list[str] = []

            for key, value in extras.items():
                if key in protected_keys or key in base:
                    skipped[key] = value
                    continue
                base[key] = value
                merged_keys.append(key)

            if log_fp:
                try:
                    if merged_keys:
                        log_fp.write("[request] provider.request_format merged: " + ", ".join(sorted(merged_keys)) + "\n")
                    if skipped:
                        log_fp.write("[request] provider.request_format skipped: " + ", ".join(sorted(skipped.keys())) + "\n")
                    log_fp.flush()
                except Exception:
                    pass

        # Provider-level extra fields are ALWAYS merged.
        # This is important for cases like {"think": false}: the caller wants to explicitly disable thinking
        # on the server side, even when UI 'show thinking' (enable_thinking) is off.
        _merge_request_extras(request_body, getattr(provider, 'request_format', None))

        # UI thinking display is controlled by enable_thinking; request-side behavior is controlled by request_format.
        # If a provider needs a specific key to *enable* thinking, put it into request_format (e.g. {"think": true}).

        if debug_log_path:
            try:
                open("debug_request.json", "w", encoding="utf-8").write(
                    json.dumps(request_body, ensure_ascii=False, indent=2)
                )
            except Exception:
                pass
        response_content = ""
        thinking_content = ""
        tokens_used = 0

        def _pretty_json(value: Any, max_chars: int = 12000) -> str:
            try:
                text = json.dumps(value, ensure_ascii=False, indent=2)
            except Exception:
                text = str(value)
            if len(text) > max_chars:
                return text[:max_chars] + "\n...（内容过长，已截断）"
            return text

        async def _read_response_bytes(resp: httpx.Response) -> bytes:
            """Safely read streaming response body for error display."""
            try:
                return await resp.aread()
            except Exception:
                # In rare cases response may already be closed; fall back to empty.
                return b""

        def _format_http_error(status_code: int, payload: Any, text_fallback: str = "") -> str:
            if isinstance(payload, dict) and payload.get('error') is not None:
                return f"HTTP 错误 {status_code}\n" + _pretty_json(payload.get('error'))
            if payload is not None:
                return f"HTTP 错误 {status_code}\n" + _pretty_json(payload)
            if text_fallback:
                return f"HTTP 错误 {status_code}: {text_fallback[:1200]}"
            return f"HTTP 错误 {status_code}"
        
        try:
            timeout_config = httpx.Timeout(self.timeout, connect=30.0)
            
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                # Non-stream mode
                if not request_body.get('stream', True):
                    resp = await client.post(
                        provider.get_chat_endpoint(),
                        headers=provider.get_headers(),
                        json=request_body
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

                        response_content = _format_http_error(resp.status_code, payload, text)
                        if on_token:
                            on_token(response_content)
                    else:
                        payload = resp.json()
                        choices = payload.get('choices', []) if isinstance(payload, dict) else []
                        if choices:
                            msg = choices[0].get('message', {}) or {}
                            content = msg.get('content', '') or ''
                            visible, embedded_thinking = thinking_parser.feed(content)
                            response_content += visible

                            thinking = (
                                msg.get('thinking', '')
                                or msg.get('reasoning', '')
                                or msg.get('reasoning_content', '')
                                or msg.get('thinking_content', '')
                                or msg.get('thoughts', '')
                                or msg.get('thought', '')
                            )
                            if enable_thinking:
                                if embedded_thinking:
                                    thinking_content += embedded_thinking
                                if thinking:
                                    thinking_content += thinking
                        else:
                            response_content = _pretty_json(payload)

                        if on_token and response_content:
                            on_token(response_content)

                    # finalize for non-stream
                    end_time = time.time()
                    response_time_ms = int((end_time - start_time) * 1000)
                    if tokens_used == 0 and response_content:
                        tokens_used = self._estimate_tokens(response_content)
                    response_message = Message(
                        role="assistant",
                        content=response_content,
                        thinking=thinking_content if thinking_content else None,
                        tokens=tokens_used,
                        response_time_ms=response_time_ms
                    )
                    try:
                        response_message.metadata.update({
                            'provider_id': getattr(provider, 'id', ''),
                            'provider_name': getattr(provider, 'name', ''),
                            'model': request_body.get('model') if isinstance(request_body, dict) else (conversation.model or provider.default_model),
                        })
                    except Exception:
                        pass
                    return response_message

                # Use streaming request
                async with client.stream(
                    'POST',
                    provider.get_chat_endpoint(),
                    headers=provider.get_headers(),
                    json=request_body
                ) as response:
                    # For streaming responses, don't call raise_for_status() before reading.
                    # Otherwise accessing response content may raise httpx.ResponseNotRead.
                    if response.status_code >= 400:
                        raw = await _read_response_bytes(response)
                        text = ""
                        payload = None
                        if raw:
                            try:
                                text = raw.decode('utf-8', errors='replace').strip()
                            except Exception:
                                text = ""
                            try:
                                payload = json.loads(text) if text else None
                            except Exception:
                                payload = None
                        response_content = _format_http_error(response.status_code, payload, text)
                        if on_token:
                            on_token(response_content)

                        end_time = time.time()
                        response_time_ms = int((end_time - start_time) * 1000)
                        if tokens_used == 0 and response_content:
                            tokens_used = self._estimate_tokens(response_content)
                        return Message(
                            role="assistant",
                            content=response_content,
                            thinking=None,
                            tokens=tokens_used,
                            response_time_ms=response_time_ms
                        )
                    
                    # Process streaming response line by line
                    buffer = ""
                    stop_stream = False
                    async for chunk in response.aiter_bytes():
                        if self._cancel_requested:
                            break

                        if stop_stream:
                            break
                        
                        buffer += chunk.decode('utf-8', errors='ignore')
                        
                        # Process complete lines
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            
                            if not line:
                                continue
                            
                            if line.startswith('data: '):
                                data = line[6:]
                                if data == '[DONE]':
                                    continue

                                if log_fp:
                                    try:
                                        log_fp.write(data + "\n")
                                        log_fp.flush()
                                    except Exception:
                                        pass
                                
                                try:
                                    chunk_data = json.loads(data)

                                    # Some OpenAI-compatible providers send errors in-band during streaming.
                                    if isinstance(chunk_data, dict) and chunk_data.get('error') is not None:
                                        response_content = "接口返回错误（stream）：\n" + _pretty_json(chunk_data.get('error'))
                                        if on_token:
                                            on_token(response_content)
                                        stop_stream = True
                                        break

                                    choices = chunk_data.get('choices', [])
                                    
                                    if choices:
                                        delta = choices[0].get('delta', {})
                                        
                                        # Handle content (may include in-band <think> tags)
                                        content = delta.get('content', '') or ''
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
                                        
                                        # Handle thinking (compat keys across providers/proxies)
                                        thinking = (
                                            delta.get('thinking', '')
                                            or delta.get('reasoning', '')
                                            or delta.get('reasoning_content', '')
                                            or delta.get('thinking_content', '')
                                            or delta.get('thoughts', '')
                                            or delta.get('thought', '')
                                        )
                                        if enable_thinking and thinking:
                                            thinking_content += thinking
                                            if on_thinking:
                                                on_thinking(thinking)
                                    
                                    # Track usage
                                    usage = chunk_data.get('usage', {})
                                    if usage:
                                        tokens_used = usage.get('total_tokens', 0)
                                        
                                except json.JSONDecodeError:
                                    if log_fp:
                                        try:
                                            log_fp.write("[JSONDecodeError]\n")
                                            log_fp.flush()
                                        except Exception:
                                            pass
                                    continue
        
        except httpx.HTTPStatusError as e:
            status_code = 0
            try:
                status_code = int(getattr(e.response, 'status_code', 0) or 0)
            except Exception:
                status_code = 0

            raw = await _read_response_bytes(e.response)
            text = ""
            payload = None
            if raw:
                try:
                    text = raw.decode('utf-8', errors='replace').strip()
                except Exception:
                    text = ""
                try:
                    payload = json.loads(text) if text else None
                except Exception:
                    payload = None

            response_content = _format_http_error(status_code or 0, payload, text)

            if on_token:
                on_token(response_content)
                
        except httpx.ConnectError as e:
            response_content = f"连接失败: 无法连接到服务器 ({str(e)[:100]})"
            if on_token:
                on_token(response_content)
                
        except httpx.TimeoutException:
            response_content = "请求超时: 服务器响应时间过长"
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
        
        # Calculate timing
        end_time = time.time()
        response_time_ms = int((end_time - start_time) * 1000)
        
        # Estimate tokens if not provided
        if tokens_used == 0 and response_content:
            tokens_used = self._estimate_tokens(response_content)
        
        # Create response message
        response_message = Message(
            role="assistant",
            content=response_content,
            thinking=thinking_content if thinking_content else None,
            tokens=tokens_used,
            response_time_ms=response_time_ms
        )

        # Record which provider/model produced this message for UI display.
        try:
            response_message.metadata.update({
                'provider_id': getattr(provider, 'id', ''),
                'provider_name': getattr(provider, 'name', ''),
                'model': request_body.get('model') if isinstance(request_body, dict) else (conversation.model or provider.default_model),
            })
        except Exception:
            pass
        
        return response_message
    
    def _build_api_messages(
        self, 
        messages: List[Message], 
        provider: Provider
    ) -> List[Dict[str, Any]]:
        """Build API-compatible message list"""
        api_messages = []
        
        for msg in messages:
            if msg.images and provider.supports_vision:
                content = []
                
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                
                for image in msg.images:
                    if image.startswith('data:'):
                        image_url = image
                    elif image.startswith(('http://', 'https://')):
                        image_url = image
                    else:
                        image_url = self._encode_image_file(image)
                    
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    })
                
                api_messages.append({"role": msg.role, "content": content})
            else:
                api_messages.append({"role": msg.role, "content": msg.content})
        
        return api_messages
    
    def _encode_image_file(self, file_path: str) -> str:
        """Encode an image file to base64 data URL"""
        try:
            import mimetypes
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = 'image/png'
            
            with open(file_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            return f"data:{mime_type};base64,{image_data}"
        except Exception as e:
            print(f"Error encoding image: {e}")
            return ""
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)
