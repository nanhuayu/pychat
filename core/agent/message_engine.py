from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from models.conversation import Conversation, Message
from models.provider import Provider

from core.llm.client import LLMClient
from core.tools.manager import McpManager
from core.tools.base import ToolContext
from core.config import load_app_config, AppConfig
from core.state.services.compression_service import CompressionService
from core.agent.policy import RunPolicy, build_compression_policy


@dataclass
class RunResult:
    status: str  # "completed" | "cancelled" | "failed"
    final_message: Optional[Message] = None
    error: Optional[str] = None


class MessageEngine:
    """Unified think-act tool loop for both chat and agent.

    - Pure core module (no Qt)
    - Streams via callbacks
    - Applies tools + state sync consistently
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        mcp_manager: McpManager,
    ) -> None:
        self._client = client
        self._mcp_manager = mcp_manager

    def _emit_step(self, on_step: Optional[Callable[[Message], None]], msg: Message) -> None:
        if not on_step:
            return
        try:
            on_step(msg)
        except Exception:
            pass

    async def _call_llm(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        on_token: Optional[Callable[[str], None]],
        on_thinking: Optional[Callable[[str], None]],
        cancel_event: Optional[threading.Event],
        debug_log_path: Optional[str],
    ) -> Message:
        return await self._client.send_message(
            provider=provider,
            conversation=conversation,
            enable_thinking=bool(policy.enable_thinking),
            enable_search=bool(policy.enable_search),
            enable_mcp=bool(policy.enable_mcp),
            on_token=on_token,
            on_thinking=on_thinking,
            debug_log_path=debug_log_path,
            cancel_event=cancel_event,
        )

    def _parse_tool_call(self, tool_call: dict) -> tuple[str, dict, Optional[str]]:
        tool_name = tool_call.get("function", {}).get("name")
        args_str = tool_call.get("function", {}).get("arguments", "{}")
        tool_call_id = tool_call.get("id")

        try:
            args = json.loads(args_str) if isinstance(args_str, str) else {}
        except Exception:
            args = {}

        return str(tool_name or ""), (args if isinstance(args, dict) else {}), tool_call_id

    def _is_tool_allowed(self, tool_name: str, policy: RunPolicy) -> bool:
        try:
            allowlist = getattr(policy, "tool_allowlist", None)
            if allowlist is not None and tool_name not in allowlist:
                return False
            if tool_name == "builtin_web_search":
                return bool(policy.enable_search)
            return bool(policy.enable_mcp)
        except Exception:
            return False

    def _build_tool_context(
        self,
        *,
        conversation: Conversation,
        provider: Provider,
        approval_callback: Optional[Callable[[str], bool]],
    ) -> ToolContext:
        work_dir = getattr(conversation, "work_dir", "") or "."
        state_dict: dict[str, Any]
        try:
            state_dict = dict(conversation.get_state().to_dict() or {})
        except Exception:
            try:
                state_dict = dict(getattr(conversation, "_state_dict", {}) or {})
            except Exception:
                state_dict = {}

        try:
            state_dict["_current_seq"] = int(conversation.current_seq_id() or 0)
        except Exception:
            state_dict["_current_seq"] = 0

        return ToolContext(
            work_dir=work_dir,
            approval_callback=approval_callback or (lambda _msg: False),
            state=state_dict,
            llm_client=self._client,
            conversation=conversation,
            provider=provider,
        )

    async def _execute_tool_call(
        self,
        *,
        tool_name: str,
        tool_args: dict,
        allowed: bool,
        policy: RunPolicy,
        context: ToolContext,
    ) -> str:
        if not allowed:
            return (
                f"Tool '{tool_name}' is disabled by current mode/settings. "
                f"(enable_search={bool(policy.enable_search)}, enable_mcp={bool(policy.enable_mcp)})"
            )
        try:
            return await self._mcp_manager.execute_tool_with_context(tool_name, tool_args, context)
        except Exception as e:
            return f"Error executing tool {tool_name}: {str(e)}"

    def _sync_state_from_context(self, conversation: Conversation, context: ToolContext) -> None:
        try:
            synced_state = {k: v for k, v in (context.state or {}).items() if not str(k).startswith("_")}
            # Treat ToolContext.state as the full serialized SessionState snapshot.
            # Replace instead of update to avoid keeping stale keys.
            try:
                from models.state import SessionState

                conversation.set_state(SessionState.from_dict(dict(synced_state)))
            except Exception:
                try:
                    conversation._state_dict = dict(synced_state)
                except Exception:
                    getattr(conversation, "_state_dict", {}).clear()
                    getattr(conversation, "_state_dict", {}).update(synced_state)
        except Exception:
            pass

    async def _maybe_manage_context(self, conversation: Conversation, provider: Provider, policy: RunPolicy) -> None:
        # Decide whether to auto-compress.
        try:
            cfg = load_app_config()
        except Exception:
            cfg = AppConfig()

        try:
            cfg_enabled = bool(getattr(getattr(cfg, "context", None), "agent_auto_compress_enabled", True))
        except Exception:
            cfg_enabled = True

        # Mode-gated compression:
        # - If policy.auto_compress_enabled is explicitly set, respect it (but still allow app_config to disable).
        # - If policy.auto_compress_enabled is None, only enable for agent-like modes.
        mode_slug = str(getattr(policy, "mode", "chat") or "chat")

        if policy.auto_compress_enabled is False:
            enabled = False
        elif policy.auto_compress_enabled is True:
            enabled = bool(cfg_enabled)
        else:
            agent_like = False
            try:
                from core.modes.manager import ModeManager

                mm = ModeManager(getattr(conversation, "work_dir", None) or None)
                agent_like = bool(mm.get(mode_slug).is_agent_like())
            except Exception:
                agent_like = mode_slug.strip().lower() in {"agent", "code", "debug"}

            enabled = bool(cfg_enabled) and bool(agent_like)

        if not enabled:
            return

        compression_policy = build_compression_policy(cfg)

        await CompressionService.manage(
            conversation=conversation,
            provider=provider,
            llm_client=self._client,
            context_window_limit=int(policy.context_window_limit),
            policy=compression_policy,
        )


    async def run(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        on_token: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        on_step: Optional[Callable[[Message], None]] = None,
        on_update: Optional[Callable[[str], None]] = None,
        approval_callback: Optional[Callable[[str], bool]] = None,
        cancel_event: Optional[threading.Event] = None,
        debug_log_path: Optional[str] = None,
    ) -> RunResult:
        turns_limit = int(getattr(policy, "max_turns", 10) or 10)
        if turns_limit <= 0:
            turns_limit = 1

        final_assistant: Optional[Message] = None

        for turn in range(turns_limit):
            if cancel_event and cancel_event.is_set():
                return RunResult(status="cancelled")

            if on_update:
                try:
                    on_update(f"--- Turn {turn + 1}/{turns_limit} ---")
                except Exception:
                    pass

            await self._maybe_manage_context(conversation, provider, policy)

            try:
                assistant_msg = await self._call_llm(
                    provider=provider,
                    conversation=conversation,
                    policy=policy,
                    on_token=on_token,
                    on_thinking=on_thinking,
                    cancel_event=cancel_event,
                    debug_log_path=debug_log_path,
                )
            except Exception as e:
                return RunResult(status="failed", error=str(e))

            # Assign seq_id and append
            try:
                assistant_msg.seq_id = conversation.next_seq_id()
            except Exception:
                pass

            self._emit_step(on_step, assistant_msg)

            conversation.add_message(assistant_msg)
            final_assistant = assistant_msg

            if cancel_event and cancel_event.is_set():
                return RunResult(status="cancelled")

            # Stop if no tool calls
            if not assistant_msg.tool_calls:
                await self._maybe_manage_context(conversation, provider, policy)
                # Capture final state snapshot for rollback/reload.
                try:
                    assistant_msg.state_snapshot = dict(getattr(conversation, "_state_dict", {}) or {})
                except Exception:
                    assistant_msg.state_snapshot = None
                return RunResult(status="completed", final_message=final_assistant)

            # Execute tools
            for tool_call in assistant_msg.tool_calls or []:
                if cancel_event and cancel_event.is_set():
                    return RunResult(status="cancelled")

                tool_name, args, tool_call_id = self._parse_tool_call(tool_call)
                allowed = self._is_tool_allowed(tool_name, policy)
                context = self._build_tool_context(
                    conversation=conversation,
                    provider=provider,
                    approval_callback=approval_callback,
                )
                result_text = await self._execute_tool_call(
                    tool_name=tool_name,
                    tool_args=args,
                    allowed=allowed,
                    policy=policy,
                    context=context,
                )
                self._sync_state_from_context(conversation, context)

                tool_msg = Message(
                    role="tool",
                    content=str(result_text),
                    tool_call_id=tool_call_id,
                )
                try:
                    tool_msg.seq_id = conversation.next_seq_id()
                except Exception:
                    pass

                try:
                    tool_msg.metadata = tool_msg.metadata or {}
                    tool_msg.metadata["name"] = tool_name
                except Exception:
                    pass

                try:
                    tool_msg.state_snapshot = dict(getattr(conversation, "_state_dict", {}) or {})
                except Exception:
                    tool_msg.state_snapshot = None

                self._emit_step(on_step, tool_msg)

                conversation.add_message(tool_msg)

        # Safety: if we exhausted turns, return best effort
        return RunResult(status="completed", final_message=final_assistant)
