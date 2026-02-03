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
from core.llm.client import LLMClient
from core.agent.runner import AgentRunner


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

    def __init__(self, client: LLMClient, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._client = client
        self._streams: dict[str, ConversationStreamState] = {}

        # Keep last request_id per conversation to tolerate late step events (e.g., tool results)
        # that may arrive after we emitted response_complete and removed the stream state.
        self._last_request_id: dict[str, str] = {}

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
        mode: str = "chat",
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
        self._last_request_id[conversation_id] = request_id

        # Signal immediately (still on main thread).
        self.stream_started.emit(conversation_id, request_id, model_name)

        # Snapshot to avoid UI thread mutating while request is in-flight.
        try:
            conversation_snapshot = Conversation.from_dict(conversation.to_dict())
        except Exception:
            conversation_snapshot = conversation

        client = self._client
        mcp_manager = client.mcp_manager

        def run_async() -> None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Use the mode passed to start()
                # mode = getattr(conversation, "mode", None) 
                
                if mode == "agent":
                    runner = AgentRunner(
                        client=client,
                        mcp_manager=mcp_manager
                    )
                    
                    async def run_agent():
                        cancel_task = asyncio.create_task(wait_for_cancel())
                        try:
                            task = await runner.run_task(
                                provider=provider,
                                conversation=conversation_snapshot,
                                task_description=f"Task for conversation {conversation_id}",
                                max_turns=20,
                                on_token=lambda t: self._raw_token.emit(conversation_id, request_id, t),
                                on_thinking=lambda t: self._raw_thinking.emit(conversation_id, request_id, t),
                                on_step=lambda m: self._raw_step.emit(conversation_id, request_id, m),
                                on_update=lambda msg: self._raw_token.emit(conversation_id, request_id, f"\n[System] {msg}\n"),
                                cancel_event=state.cancel_event
                            )
                            return task
                        finally:
                            cancel_task.cancel()

                    async def wait_for_cancel():
                        while not state.cancel_event.is_set():
                            await asyncio.sleep(0.1)
                        # The runner checks cancel_event internally, so we don't need to explicitly call cancel() on runner.
                        # But we need to ensure run_task exits.
                        pass

                    task_result = loop.run_until_complete(run_agent())
                    
                    if task_result.status == "completed":
                        # In Agent mode, request a final summary from the agent
                        # This serves as the "session compression" or "summary"
                        try:
                            summary_instruction = Message(
                                role="user", 
                                content="任务已完成。请生成一份简明扼要的会话总结（Session Summary），概述已完成的工作和当前状态。"
                            )
                            conversation_snapshot.messages.append(summary_instruction)
                            
                            async def fetch_summary():
                                return await client.send_message(
                                    provider,
                                    conversation_snapshot,
                                    on_token=lambda t: self._raw_token.emit(conversation_id, request_id, t),
                                    on_thinking=lambda t: self._raw_thinking.emit(conversation_id, request_id, t),
                                    enable_search=False,
                                    enable_mcp=False # No tools for summary
                                )
                            
                            summary_msg = loop.run_until_complete(fetch_summary())
                            self._raw_complete.emit(conversation_id, request_id, summary_msg)
                            
                        except Exception as e:
                            # If summary fails, just emit None
                            self._raw_complete.emit(conversation_id, request_id, None)
                    elif task_result.status == "cancelled":
                        self._raw_error.emit(conversation_id, request_id, "任务已取消")
                    else:
                        self._raw_error.emit(conversation_id, request_id, f"任务结束: {task_result.status}")

                else:
                    # Chat Mode (Legacy Loop)
                    max_turns = 10
                    turns = 0
                    current_conversation = conversation_snapshot
                    final_response: Optional[Message] = None

                    async def chat_step() -> Message:
                        return await client.send_message(
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

                        if state.cancel_event.is_set():
                            msg = None
                            break
                        
                        if not msg:
                            break 

                        if msg.tool_calls:
                            self._raw_step.emit(conversation_id, request_id, msg)
                            current_conversation.messages.append(msg)
                            
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
                                
                                work_dir = getattr(current_conversation, "work_dir", "")
                                
                                # Use ToolContext to enforce permissions
                                from core.tools.base import ToolContext
                                
                                # TODO: Connect to UI for manual approval if needed
                                async def ui_approval_callback(msg: str) -> bool:
                                    # For Chat Mode, we currently auto-deny if not auto-approved by settings
                                    # In future, emit signal to UI to ask user
                                    return False
                                
                                context = ToolContext(
                                    work_dir=work_dir or ".",
                                    approval_callback=ui_approval_callback
                                )

                                # Enforce tool toggles:
                                # - Search tool is allowed only when enable_search is True.
                                # - All other tools (system + MCP) require enable_mcp.
                                allowed = False
                                try:
                                    if str(tool_name) == "builtin_web_search":
                                        allowed = bool(enable_search)
                                    else:
                                        allowed = bool(enable_mcp)
                                except Exception:
                                    allowed = False

                                if not allowed:
                                    result_text = (
                                        f"Tool '{tool_name}' is disabled by current mode/settings. "
                                        f"(enable_search={bool(enable_search)}, enable_mcp={bool(enable_mcp)})"
                                    )
                                else:
                                    result_text = loop.run_until_complete(
                                        mcp_manager.execute_tool_with_context(tool_name, tool_args, context)
                                    )
                                
                                tool_msg = Message(
                                    role="tool",
                                    content=str(result_text),
                                    tool_call_id=tool_call_id,
                                    metadata={"name": tool_name}
                                )
                                
                                self._raw_step.emit(conversation_id, request_id, tool_msg)
                                current_conversation.messages.append(tool_msg)
                                
                            turns += 1
                            continue
                        else:
                            final_response = msg
                            break

                    loop.close()
                    if final_response:
                        self._raw_complete.emit(conversation_id, request_id, final_response)
                    elif state.cancel_event.is_set():
                        self._raw_error.emit(conversation_id, request_id, "已取消生成")
                    else:
                        self._raw_error.emit(conversation_id, request_id, "生成未能完成")
                    
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
        if state and state.request_id == request_id:
            # Reset text buffers for the next turn.
            state.visible_text = ""
            state.thinking_text = ""
            self.response_step.emit(conversation_id, request_id, message)
            return

        # If the stream has already completed and we popped the state, still allow late step events
        # (common for tool-result UI updates) as long as they match the last request id.
        if self._last_request_id.get(conversation_id) == request_id:
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
