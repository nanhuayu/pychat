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

import json
import asyncio
import threading
import uuid
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import QObject, pyqtSignal

from models.conversation import Conversation, Message
from models.provider import Provider
from models.streaming import ConversationStreamState
from services.chat_service import ChatService


class StreamManager(QObject):
    """Orchestrates LLM streaming per conversation, including Tool Calls."""

    # Public signals (main-thread only)
    stream_started = pyqtSignal(str, str, str)          # conversation_id, request_id, model
    token_received = pyqtSignal(str, str, str)          # conversation_id, request_id, token
    thinking_received = pyqtSignal(str, str, str)       # conversation_id, request_id, thinking
    response_step = pyqtSignal(str, str, object)        # conversation_id, request_id, Message (Intermediate step)
    response_complete = pyqtSignal(str, str, object)    # conversation_id, request_id, Message (Final)
    response_error = pyqtSignal(str, str, str)          # conversation_id, request_id, error

    # Internal raw signals (emitted from worker threads)
    _raw_token = pyqtSignal(str, str, str)
    _raw_thinking = pyqtSignal(str, str, str)
    _raw_step = pyqtSignal(str, str, object)
    _raw_complete = pyqtSignal(str, str, object)
    _raw_error = pyqtSignal(str, str, str)

    def __init__(self, chat_service: ChatService, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._chat_service = chat_service
        self._streams: dict[str, ConversationStreamState] = {}

        self._raw_token.connect(self._on_raw_token)
        self._raw_thinking.connect(self._on_raw_thinking)
        self._raw_step.connect(self._on_raw_step)
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
        enable_search: bool = False,
        enable_mcp: bool = False,
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
        mcp_manager = chat_service.mcp_manager

        def run_async() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Maximum conversation turns to prevent infinite loops
                max_turns = 10
                turns = 0
                
                # Current working conversation context (evolves with tool calls)
                current_conversation = conversation_snapshot
                
                final_response: Optional[Message] = None

                async def chat_step() -> Message:
                    return await chat_service.send_message(
                        provider,
                        current_conversation,
                        on_token=lambda t: self._raw_token.emit(conversation_id, request_id, t),
                        on_thinking=lambda t: self._raw_thinking.emit(conversation_id, request_id, t),
                        enable_thinking=bool(enable_thinking),
                        enable_search=bool(enable_search),
                        enable_mcp=bool(enable_mcp),
                        debug_log_path=debug_log_path,
                        cancel_event=state.cancel_event,
                    )

                while turns < max_turns:
                    if state.cancel_event.is_set():
                        break
                        
                    msg = loop.run_until_complete(chat_step())
                    
                    if not msg:
                        break # Error or empty?

                    # If this message has tool calls, it's an intermediate step
                    if msg.tool_calls:
                        # 1. Emit the Assistant's "Call Tool" message as a step
                        self._raw_step.emit(conversation_id, request_id, msg)
                        
                        # 2. Append to current context
                        current_conversation.messages.append(msg)
                        
                        # 3. Serialize executions
                        for tc in msg.tool_calls:
                            if state.cancel_event.is_set():
                                break
                                
                            tool_name = tc.get("function", {}).get("name")
                            tool_args_str = tc.get("function", {}).get("arguments", "{}")
                            tool_call_id = tc.get("id")
                            
                            try:
                                tool_args = json.loads(tool_args_str)
                            except Exception:
                                tool_args = {}
                                
                            # Notify UI/log? We can emit a token?
                            # self._raw_token.emit(conversation_id, request_id, f"\n[Executing {tool_name}...]\n")
                            
                            # Execute
                            work_dir = getattr(current_conversation, "work_dir", "")
                            result_text = loop.run_until_complete(
                                mcp_manager.call_tool(tool_name, tool_args, work_dir=work_dir)
                            )
                            
                            # Create Tool Message
                            tool_msg = Message(
                                role="tool",
                                content=str(result_text),
                                tool_call_id=tool_call_id,
                                metadata={"name": tool_name}
                            )
                            
                            # Emit Tool Result as a step
                            self._raw_step.emit(conversation_id, request_id, tool_msg)
                            
                            # Append to context
                            current_conversation.messages.append(tool_msg)
                            
                        turns += 1
                        # Reset visible text state allows new tokens to stream cleanly?
                        # StreamManager state accumulation issues?
                        # state.visible_text accumulates EVERYTHING?
                        # Actually UI ChatView appends new bubble for each message.
                        # We should reset state.visible_text for the NEXT turn.
                        # But wait, raw tokens are just emitted.
                        continue
                    else:
                        # Final answer
                        final_response = msg
                        break

                loop.close()
                if final_response:
                    self._raw_complete.emit(conversation_id, request_id, final_response)
                else:
                    # Cancelled or looped out
                    pass
                    
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

    def _on_raw_step(self, conversation_id: str, request_id: str, message: object) -> None:
        """Handle intermediate steps (tool calls / tool results)."""
        state = self._streams.get(conversation_id)
        if not state or state.request_id != request_id:
            return
        # Reset text buffers for the next turn?
        # If we just finished an Assistant turn (with tool_calls), state.visible_text has that content.
        # We emit the message object to UI. UI appends it.
        # Ideally we clear state.visible_text so future tokens start fresh?
        state.visible_text = ""
        state.thinking_text = ""
        self.response_step.emit(conversation_id, request_id, message)

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
