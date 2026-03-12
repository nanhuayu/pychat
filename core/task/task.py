"""Unified task execution engine.

Replaces ``core.agent.message_engine.MessageEngine`` with:
- Retry with exponential backoff on transient LLM errors
- Context-overflow recovery (condense → retry)
- Unified condense before each LLM call
- Clean callback-based event streaming (no Qt)
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Optional

from models.conversation import Conversation, Message
from models.provider import Provider

from core.llm.client import LLMClient
from core.tools.base import ToolContext
from core.tools.manager import McpManager
from core.config import load_app_config, AppConfig
from core.task.types import (
    RunPolicy,
    TaskEvent,
    TaskEventKind,
    TaskResult,
    TaskStatus,
)
from core.task.retry import (
    ErrorKind,
    classify_error,
    is_retryable,
    retry_with_backoff,
)
from core.task.repetition import ToolRepetitionDetector

logger = logging.getLogger(__name__)

# Modes where the agent should auto-continue when LLM returns text
# without tool calls (nudge it to keep working or call attempt_completion).
_AUTO_CONTINUE_MODES = frozenset({"agent", "code", "debug"})
_MAX_NUDGE_COUNT = 3

_NUDGE_TEXT = (
    "[AUTO-CONTINUE] You responded without using any tools. "
    "If you have not completed the task, please continue using the available tools. "
    "If the task is complete, call the `attempt_completion` tool to present your result. "
    "Do not simply describe what you would do — take action."
)

_REPETITION_WARNING = (
    "[WARNING] You have called the same tool with identical arguments multiple times consecutively. "
    "This is not making progress. Please try a different approach, use different arguments, "
    "or call `attempt_completion` if done."
)


class Task:
    """Unified think-act tool loop.

    Pure-core module (no Qt).  Streams progress via an ``on_event`` callback.
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        mcp_manager: McpManager,
    ) -> None:
        self._client = client
        self._mcp_manager = mcp_manager
        # Hook lists: callables invoked at each turn boundary
        self._pre_turn_hooks: list[Callable] = []
        self._post_turn_hooks: list[Callable] = []

    def add_pre_turn_hook(self, hook: Callable) -> None:
        """Register a hook called before each LLM turn. Signature: (conversation, turn, policy) -> None"""
        self._pre_turn_hooks.append(hook)

    def add_post_turn_hook(self, hook: Callable) -> None:
        """Register a hook called after each LLM turn. Signature: (conversation, turn, assistant_msg) -> None"""
        self._post_turn_hooks.append(hook)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        on_event: Optional[Callable[[TaskEvent], None]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        approval_callback: Optional[Callable[[str], bool]] = None,
        cancel_event: Optional[threading.Event] = None,
        debug_log_path: Optional[str] = None,
    ) -> TaskResult:
        turns_limit = max(1, int(policy.max_turns or 20))
        final_assistant: Optional[Message] = None
        nudge_count = 0
        repetition_detector = ToolRepetitionDetector()

        def emit(kind: TaskEventKind, turn: int = 0, **kw: Any) -> None:
            if on_event:
                try:
                    on_event(TaskEvent(kind=kind, turn=turn, **kw))
                except Exception:
                    pass

        for turn in range(turns_limit):
            if cancel_event and cancel_event.is_set():
                return TaskResult(status=TaskStatus.CANCELLED)

            emit(TaskEventKind.TURN_START, turn=turn + 1, detail=f"Turn {turn + 1}/{turns_limit}")

            # --- Pre-turn hooks ---
            for hook in self._pre_turn_hooks:
                try:
                    hook(conversation, turn + 1, policy)
                except Exception as he:
                    logger.debug("Pre-turn hook error: %s", he)

            # --- Inject user context (XML tags) on first turn ---
            if turn == 0:
                self._inject_user_context(conversation, policy)

            # --- Condense context ---
            await self._maybe_condense(conversation, provider, policy)

            # --- LLM call with retry ---
            try:
                assistant_msg = await self._call_llm_with_retry(
                    provider=provider,
                    conversation=conversation,
                    policy=policy,
                    on_token=on_token,
                    on_thinking=on_thinking,
                    cancel_event=cancel_event,
                    debug_log_path=debug_log_path,
                    emit=lambda **kw: emit(turn=turn + 1, **kw),
                )
            except Exception as e:
                kind = classify_error(e)
                # Context overflow: try emergency condense + one more attempt
                if kind == ErrorKind.CONTEXT_OVERFLOW:
                    try:
                        await self._force_condense(conversation, provider, policy)
                        assistant_msg = await self._call_llm_raw(
                            provider=provider,
                            conversation=conversation,
                            policy=policy,
                            on_token=on_token,
                            on_thinking=on_thinking,
                            cancel_event=cancel_event,
                            debug_log_path=debug_log_path,
                        )
                    except Exception as e2:
                        return TaskResult(status=TaskStatus.FAILED, error=str(e2))
                else:
                    return TaskResult(status=TaskStatus.FAILED, error=str(e))

            # Assign seq_id and append
            try:
                assistant_msg.seq_id = conversation.next_seq_id()
            except Exception:
                pass

            emit(TaskEventKind.STEP, turn=turn + 1, data=assistant_msg)
            conversation.add_message(assistant_msg)
            final_assistant = assistant_msg

            # --- Post-turn hooks ---
            for hook in self._post_turn_hooks:
                try:
                    hook(conversation, turn + 1, assistant_msg)
                except Exception as he:
                    logger.debug("Post-turn hook error: %s", he)

            if cancel_event and cancel_event.is_set():
                return TaskResult(status=TaskStatus.CANCELLED)

            # No tool calls → check auto-continue or finish
            if not assistant_msg.tool_calls:
                mode_slug = (policy.mode or "chat").lower()
                if mode_slug in _AUTO_CONTINUE_MODES and nudge_count < _MAX_NUDGE_COUNT:
                    # Auto-continue: inject nudge and loop again
                    nudge_count += 1
                    logger.info("Auto-continue nudge %d/%d (mode=%s)", nudge_count, _MAX_NUDGE_COUNT, mode_slug)
                    nudge_msg = Message(role="user", content=_NUDGE_TEXT)
                    try:
                        nudge_msg.seq_id = conversation.next_seq_id()
                    except Exception:
                        pass
                    emit(TaskEventKind.STEP, turn=turn + 1, data=nudge_msg)
                    conversation.add_message(nudge_msg)
                    continue
                # Non-agent mode or nudge budget exhausted → finish
                await self._maybe_condense(conversation, provider, policy)
                self._attach_state_snapshot(conversation, assistant_msg)
                return TaskResult(status=TaskStatus.COMPLETED, final_message=final_assistant)

            # --- Execute tools ---
            # Reset nudge counter when LLM successfully uses tools
            nudge_count = 0

            for tool_call in assistant_msg.tool_calls or []:
                if cancel_event and cancel_event.is_set():
                    return TaskResult(status=TaskStatus.CANCELLED)

                tool_name, args, tool_call_id = self._parse_tool_call(tool_call)

                # --- Repetition detection ---
                if repetition_detector.record(tool_name, args if isinstance(args, dict) else {}):
                    logger.warning("Tool repetition detected: %s", tool_name)
                    warn_msg = Message(role="user", content=_REPETITION_WARNING)
                    try:
                        warn_msg.seq_id = conversation.next_seq_id()
                    except Exception:
                        pass
                    emit(TaskEventKind.STEP, turn=turn + 1, data=warn_msg)
                    conversation.add_message(warn_msg)
                    repetition_detector.reset()
                    break  # Skip executing, let LLM reconsider

                allowed = self._is_tool_allowed(tool_name, policy)

                context = self._build_tool_context(
                    conversation=conversation,
                    provider=provider,
                    approval_callback=approval_callback,
                )
                result_text = await self._execute_tool(
                    tool_name=tool_name,
                    tool_args=args,
                    allowed=allowed,
                    policy=policy,
                    context=context,
                )

                # --- Handle sub-task delegation ---
                subtask_req = (context.state or {}).get("_pending_subtask")
                if subtask_req and isinstance(subtask_req, dict):
                    context.state.pop("_pending_subtask", None)
                    subtask_result = await self._run_subtask(
                        subtask_req=subtask_req,
                        provider=provider,
                        conversation=conversation,
                        on_event=on_event,
                        on_token=on_token,
                        on_thinking=on_thinking,
                        approval_callback=approval_callback,
                        cancel_event=cancel_event,
                    )
                    result_text = str(subtask_result)

                # --- Handle attempt_completion signal ---
                if (context.state or {}).get("_task_completed"):
                    completion_result = (context.state or {}).get("_completion_result", "")
                    self._sync_state(conversation, context)
                    tool_msg = Message(role="tool", content=str(result_text), tool_call_id=tool_call_id)
                    try:
                        tool_msg.seq_id = conversation.next_seq_id()
                    except Exception:
                        pass
                    emit(TaskEventKind.STEP, turn=turn + 1, data=tool_msg)
                    conversation.add_message(tool_msg)
                    return TaskResult(status=TaskStatus.COMPLETED, final_message=assistant_msg)

                self._sync_state(conversation, context)

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
                self._attach_state_snapshot(conversation, tool_msg)
                emit(TaskEventKind.STEP, turn=turn + 1, data=tool_msg)
                conversation.add_message(tool_msg)

        return TaskResult(status=TaskStatus.COMPLETED, final_message=final_assistant)

    # ------------------------------------------------------------------
    # Sub-task execution (multi-agent)
    # ------------------------------------------------------------------

    async def _run_subtask(
        self,
        *,
        subtask_req: dict,
        provider: Provider,
        conversation: Conversation,
        on_event,
        on_token,
        on_thinking,
        approval_callback,
        cancel_event,
    ) -> str:
        """Spawn a child Task in an independent conversation context."""
        mode_slug = subtask_req.get("mode", "code")
        message = subtask_req.get("message", "")

        try:
            from core.task.builder import build_run_policy

            child_policy = build_run_policy(mode_slug=mode_slug)

            child_conv = Conversation(
                title=f"Sub-task: {mode_slug}",
                messages=[Message(role="user", content=message)],
                mode=mode_slug,
            )
            # Inherit work_dir from parent
            try:
                child_conv.work_dir = getattr(conversation, "work_dir", ".") or "."
            except Exception:
                pass

            child_task = Task(client=self._client, mcp_manager=self._mcp_manager)
            result = await child_task.run(
                provider=provider,
                conversation=child_conv,
                policy=child_policy,
                on_event=on_event,
                on_token=on_token,
                on_thinking=on_thinking,
                approval_callback=approval_callback,
                cancel_event=cancel_event,
            )

            if result.status == TaskStatus.COMPLETED and result.final_message:
                return result.final_message.content or "Sub-task completed (no output)."
            elif result.status == TaskStatus.FAILED:
                return f"Sub-task failed: {result.error}"
            elif result.status == TaskStatus.CANCELLED:
                return "Sub-task was cancelled."
            return "Sub-task completed."
        except Exception as e:
            logger.error("Sub-task failed: %s", e)
            return f"Sub-task error: {e}"

    # ------------------------------------------------------------------
    # User context injection
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_user_context(conversation: Conversation, policy: RunPolicy) -> None:
        """Inject environment/workspace/summary XML into user messages."""
        try:
            from core.prompts.user_context import inject_user_context

            inject_user_context(
                conversation,
                include_environment=True,
                include_workspace=bool(policy.enable_mcp),
                include_summary=True,
                inject_mode="first",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # LLM call with retry
    # ------------------------------------------------------------------

    async def _call_llm_with_retry(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        on_token,
        on_thinking,
        cancel_event,
        debug_log_path,
        emit,
    ) -> Message:
        retry_policy = policy.retry

        def on_retry(attempt: int, delay: float, error: str) -> None:
            logger.warning("LLM retry %d after %.1fs: %s", attempt, delay, error)
            emit(kind=TaskEventKind.RETRY, detail=f"Retry {attempt} in {delay:.0f}s: {error}")

        return await retry_with_backoff(
            lambda: self._call_llm_raw(
                provider=provider,
                conversation=conversation,
                policy=policy,
                on_token=on_token,
                on_thinking=on_thinking,
                cancel_event=cancel_event,
                debug_log_path=debug_log_path,
            ),
            policy=retry_policy,
            on_retry=on_retry,
        )

    async def _call_llm_raw(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        on_token,
        on_thinking,
        cancel_event,
        debug_log_path,
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

    # ------------------------------------------------------------------
    # Context management (condense)
    # ------------------------------------------------------------------

    async def _maybe_condense(
        self,
        conversation: Conversation,
        provider: Provider,
        policy: RunPolicy,
    ) -> None:
        """Condense if app config allows and policy doesn't force OFF."""
        try:
            cfg = load_app_config()
        except Exception:
            cfg = AppConfig()

        try:
            cfg_enabled = bool(getattr(getattr(cfg, "context", None), "agent_auto_compress_enabled", True))
        except Exception:
            cfg_enabled = True

        if policy.auto_compress_enabled is False:
            return
        if not cfg_enabled:
            return

        from core.context.condenser import ContextCondenser as Condenser
        condenser = Condenser(self._client)
        await condenser.auto_condense(
            conversation=conversation,
            provider=provider,
            context_window_limit=int(policy.context_window_limit),
            app_config=cfg,
        )

    async def _force_condense(
        self,
        conversation: Conversation,
        provider: Provider,
        policy: RunPolicy,
    ) -> None:
        """Emergency condense on context overflow — aggressive keep_last_n."""
        from core.context.condenser import ContextCondenser as Condenser
        condenser = Condenser(self._client)
        state = conversation.get_state()
        await condenser.condense_state(conversation, provider, state, keep_last_n=3)
        conversation.set_state(state)
        logger.info("Emergency condense complete")

    # ------------------------------------------------------------------
    # Tool execution helpers
    # ------------------------------------------------------------------

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
            allowlist = policy.tool_allowlist
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

    async def _execute_tool(
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
            return f"Error executing tool {tool_name}: {e}"

    def _sync_state(self, conversation: Conversation, context: ToolContext) -> None:
        try:
            synced = {k: v for k, v in (context.state or {}).items() if not str(k).startswith("_")}
            try:
                from models.state import SessionState
                conversation.set_state(SessionState.from_dict(dict(synced)))
            except Exception:
                try:
                    conversation._state_dict = dict(synced)
                except Exception:
                    pass
        except Exception:
            pass

    def _attach_state_snapshot(self, conversation: Conversation, msg: Message) -> None:
        try:
            msg.state_snapshot = dict(getattr(conversation, "_state_dict", {}) or {})
        except Exception:
            msg.state_snapshot = None
