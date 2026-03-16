from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from models.conversation import Conversation, Message
from models.provider import Provider
from models.streaming import ConversationStreamState

from core.llm.client import LLMClient
from core.tools.manager import ToolManager
from core.task.task import Task
from core.task.types import RunPolicy, TaskResult, TaskStatus, TaskEvent, TaskEventKind


logger = logging.getLogger(__name__)


class MessageRuntime(QObject):
    """UI runtime bridge for MessageEngine.

    - Owns worker threads + request routing
    - Exposes Qt signals (main-thread)
    - Keeps per-conversation streaming state for UI restore

    Core logic lives in `core.agent.message_engine.MessageEngine`.
    """

    stream_started = pyqtSignal(str, str, str)          # conversation_id, request_id, model
    token_received = pyqtSignal(str, str, str)          # conversation_id, request_id, token
    thinking_received = pyqtSignal(str, str, str)       # conversation_id, request_id, thinking
    response_step = pyqtSignal(str, str, object)        # conversation_id, request_id, Message
    response_complete = pyqtSignal(str, str, object)    # conversation_id, request_id, Message
    response_error = pyqtSignal(str, str, str)          # conversation_id, request_id, error
    retry_attempt = pyqtSignal(str, str, str)            # conversation_id, request_id, detail

    _raw_token = pyqtSignal(str, str, str)
    _raw_thinking = pyqtSignal(str, str, str)
    _raw_step = pyqtSignal(str, str, object)
    _raw_complete = pyqtSignal(str, str, object)
    _raw_error = pyqtSignal(str, str, str)
    _raw_retry = pyqtSignal(str, str, str)

    def __init__(self, client: LLMClient, tool_manager: Optional[ToolManager] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._client = client
        self._tool_manager = tool_manager or client.tool_manager
        self._engine = Task(client=self._client, tool_manager=self._tool_manager)

        self._streams: dict[str, ConversationStreamState] = {}
        self._last_request_id: dict[str, str] = {}

        self._raw_token.connect(self._on_raw_token)
        self._raw_thinking.connect(self._on_raw_thinking)
        self._raw_step.connect(self._on_raw_step)
        self._raw_complete.connect(self._on_raw_complete)
        self._raw_error.connect(self._on_raw_error)
        self._raw_retry.connect(self._on_raw_retry)

    def is_streaming(self, conversation_id: str) -> bool:
        return bool(conversation_id) and conversation_id in self._streams

    def get_state(self, conversation_id: str) -> Optional[ConversationStreamState]:
        return self._streams.get(conversation_id)

    def start(
        self,
        provider: Provider,
        conversation: Conversation,
        *,
        policy: RunPolicy,
        debug_log_path: Optional[str] = None,
    ) -> Optional[ConversationStreamState]:
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
        self._last_request_id[conversation_id] = request_id

        self.stream_started.emit(conversation_id, request_id, model_name)

        try:
            conversation_snapshot = Conversation.from_dict(conversation.to_dict())
        except Exception:
            conversation_snapshot = conversation

        def run_worker() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                def on_token(t: str) -> None:
                    self._raw_token.emit(conversation_id, request_id, t)

                def on_thinking(t: str) -> None:
                    self._raw_thinking.emit(conversation_id, request_id, t)

                def on_step(m: Message) -> None:
                    self._raw_step.emit(conversation_id, request_id, m)

                async def run() -> None:
                    def on_event(evt: TaskEvent) -> None:
                        if evt.kind == TaskEventKind.STEP and isinstance(evt.data, Message):
                            on_step(evt.data)
                        elif evt.kind == TaskEventKind.RETRY:
                            self._raw_retry.emit(conversation_id, request_id, evt.detail or "")

                    result = await self._engine.run(
                        provider=provider,
                        conversation=conversation_snapshot,
                        policy=policy,
                        on_event=on_event,
                        on_token=on_token,
                        on_thinking=on_thinking,
                        cancel_event=state.cancel_event,
                        debug_log_path=debug_log_path,
                    )
                    if result.status == TaskStatus.CANCELLED:
                        self._raw_error.emit(conversation_id, request_id, "已取消生成")
                        return
                    if result.status == TaskStatus.FAILED:
                        self._raw_error.emit(conversation_id, request_id, result.error or "生成失败")
                        return
                    self._raw_complete.emit(conversation_id, request_id, result.final_message)

                loop.run_until_complete(run())
                loop.run_until_complete(loop.shutdown_asyncgens())
                try:
                    loop.run_until_complete(loop.shutdown_default_executor())
                except Exception as exc:
                    logger.debug("Failed to shutdown runtime default executor: %s", exc)
                loop.close()

            except Exception as e:
                self._raw_error.emit(conversation_id, request_id, str(e))

        threading.Thread(target=run_worker, daemon=True).start()
        return state

    def cancel(self, conversation_id: str) -> None:
        state = self._streams.get(conversation_id)
        if state:
            state.cancel()

    # ===== Raw -> main thread normalization =====

    def _accept_event(self, conversation_id: str, request_id: str) -> bool:
        if not conversation_id or not request_id:
            return False
        live = self._streams.get(conversation_id)
        if live and live.request_id == request_id:
            return True
        return self._last_request_id.get(conversation_id) == request_id

    def _on_raw_token(self, conversation_id: str, request_id: str, token: str) -> None:
        if not self._accept_event(conversation_id, request_id):
            return
        state = self._streams.get(conversation_id)
        if state:
            try:
                state.visible_text += token
            except Exception as exc:
                logger.debug("Failed to append visible streaming token: %s", exc)
        self.token_received.emit(conversation_id, request_id, token)

    def _on_raw_thinking(self, conversation_id: str, request_id: str, thinking: str) -> None:
        if not self._accept_event(conversation_id, request_id):
            return
        state = self._streams.get(conversation_id)
        if state:
            try:
                state.thinking_text += thinking
            except Exception as exc:
                logger.debug("Failed to append thinking streaming token: %s", exc)
        self.thinking_received.emit(conversation_id, request_id, thinking)

    def _on_raw_step(self, conversation_id: str, request_id: str, message: Message) -> None:
        if not self._accept_event(conversation_id, request_id):
            return

        # When we publish an assistant step (tool_calls), the UI will finish the current bubble.
        # Reset the streaming buffers so switching conversations can restore the *next* bubble cleanly.
        try:
            if isinstance(message, Message) and getattr(message, "role", "") == "assistant":
                state = self._streams.get(conversation_id)
                if state:
                    state.visible_text = ""
                    state.thinking_text = ""
        except Exception as exc:
            logger.debug("Failed to reset streaming buffers after assistant step: %s", exc)

        self.response_step.emit(conversation_id, request_id, message)

    def _on_raw_complete(self, conversation_id: str, request_id: str, message: Optional[Message]) -> None:
        if not self._accept_event(conversation_id, request_id):
            return
        # Cleanup live state
        try:
            self._streams.pop(conversation_id, None)
        except Exception as exc:
            logger.debug("Failed to clear live stream state on completion: %s", exc)
        self.response_complete.emit(conversation_id, request_id, message)

    def _on_raw_error(self, conversation_id: str, request_id: str, error: str) -> None:
        if not self._accept_event(conversation_id, request_id):
            return
        try:
            self._streams.pop(conversation_id, None)
        except Exception as exc:
            logger.debug("Failed to clear live stream state on error: %s", exc)
        self.response_error.emit(conversation_id, request_id, error)

    def _on_raw_retry(self, conversation_id: str, request_id: str, detail: str) -> None:
        if not self._accept_event(conversation_id, request_id):
            return
        self.retry_attempt.emit(conversation_id, request_id, detail)
