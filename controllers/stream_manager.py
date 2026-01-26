"""Streaming manager.

Goal
- Keep async/threading + request routing out of UI code.
- Support concurrent streaming per conversation.
- Provide per-request cancellation.

Design
- Background thread runs an asyncio event loop and calls ChatService.send_message.
- Background thread emits *raw* Qt signals.
- Raw signals are processed on the main thread to update per-conversation state,
  then re-emitted as public signals for UI to consume.

This avoids mutating shared state from background threads.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from models.conversation import Conversation, Message
from models.provider import Provider
from models.streaming import ConversationStreamState
from services.chat_service import ChatService


class StreamManager(QObject):
    """Orchestrates LLM streaming per conversation."""

    # Public signals (main-thread only)
    stream_started = pyqtSignal(str, str, str)          # conversation_id, request_id, model
    token_received = pyqtSignal(str, str, str)          # conversation_id, request_id, token
    thinking_received = pyqtSignal(str, str, str)       # conversation_id, request_id, thinking
    response_complete = pyqtSignal(str, str, object)    # conversation_id, request_id, Message
    response_error = pyqtSignal(str, str, str)          # conversation_id, request_id, error

    # Internal raw signals (emitted from worker threads)
    _raw_token = pyqtSignal(str, str, str)
    _raw_thinking = pyqtSignal(str, str, str)
    _raw_complete = pyqtSignal(str, str, object)
    _raw_error = pyqtSignal(str, str, str)

    def __init__(self, chat_service: ChatService, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._chat_service = chat_service
        self._streams: dict[str, ConversationStreamState] = {}

        self._raw_token.connect(self._on_raw_token)
        self._raw_thinking.connect(self._on_raw_thinking)
        self._raw_complete.connect(self._on_raw_complete)
        self._raw_error.connect(self._on_raw_error)

    def is_streaming(self, conversation_id: str) -> bool:
        return bool(conversation_id) and conversation_id in self._streams

    def get_state(self, conversation_id: str) -> Optional[ConversationStreamState]:
        return self._streams.get(conversation_id)

    def start(
        self,
        provider: Provider,
        conversation: Conversation,
        *,
        enable_thinking: bool,
        debug_log_path: Optional[str] = None,
    ) -> Optional[ConversationStreamState]:
        """Start streaming for a conversation.

        Returns the created stream state, or None if conversation_id is missing.
        """
        conversation_id = getattr(conversation, "id", "") or ""
        if not conversation_id:
            return None

        request_id = str(uuid.uuid4())
        model_name = (conversation.model or provider.default_model or "")

        state = ConversationStreamState(
            conversation_id=conversation_id,
            request_id=request_id,
            model=model_name,
        )
        self._streams[conversation_id] = state

        # Signal immediately (still on main thread).
        self.stream_started.emit(conversation_id, request_id, model_name)

        # Snapshot to avoid UI thread mutating while request is in-flight.
        try:
            conversation_snapshot = Conversation.from_dict(conversation.to_dict())
        except Exception:
            conversation_snapshot = conversation

        chat_service = self._chat_service

        def run_async() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def chat() -> Message:
                    return await chat_service.send_message(
                        provider,
                        conversation_snapshot,
                        on_token=lambda t: self._raw_token.emit(conversation_id, request_id, t),
                        on_thinking=lambda t: self._raw_thinking.emit(conversation_id, request_id, t),
                        enable_thinking=bool(enable_thinking),
                        debug_log_path=debug_log_path,
                        cancel_event=state.cancel_event,
                    )

                resp = loop.run_until_complete(chat())
                loop.close()
                self._raw_complete.emit(conversation_id, request_id, resp)
            except Exception as e:
                self._raw_error.emit(conversation_id, request_id, str(e))

        threading.Thread(target=run_async, daemon=True).start()
        return state

    def cancel(self, conversation_id: str) -> None:
        state = self._streams.get(conversation_id)
        if state:
            state.cancel()

    # ===== Raw signal handlers (main thread) =====

    def _on_raw_token(self, conversation_id: str, request_id: str, token: str) -> None:
        state = self._streams.get(conversation_id)
        if not state or state.request_id != request_id:
            return
        try:
            state.visible_text += str(token or "")
        except Exception:
            return
        self.token_received.emit(conversation_id, request_id, token)

    def _on_raw_thinking(self, conversation_id: str, request_id: str, thinking: str) -> None:
        state = self._streams.get(conversation_id)
        if not state or state.request_id != request_id:
            return
        try:
            state.thinking_text += str(thinking or "")
        except Exception:
            pass
        self.thinking_received.emit(conversation_id, request_id, thinking)

    def _on_raw_complete(self, conversation_id: str, request_id: str, response: object) -> None:
        state = self._streams.get(conversation_id)
        if not state or state.request_id != request_id:
            return
        # Remove first to unblock UI immediately.
        self._streams.pop(conversation_id, None)
        self.response_complete.emit(conversation_id, request_id, response)

    def _on_raw_error(self, conversation_id: str, request_id: str, error: str) -> None:
        state = self._streams.get(conversation_id)
        if not state or state.request_id != request_id:
            return
        self._streams.pop(conversation_id, None)
        self.response_error.emit(conversation_id, request_id, error)
