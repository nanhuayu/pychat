"""Unified task execution engine - main coordinator.

Simplified from 574 lines to ~200 lines by extracting:
- LLMExecutor: LLM API calls with retry
- ToolExecutor: Tool execution and state management
- EventEmitter: Event streaming

This module now focuses on orchestration:
- Turn-based execution loop
- Hook management
- Auto-continue logic
- Sub-task delegation
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from models.conversation import Conversation, Message
from models.provider import Provider

from core.llm.client import LLMClient
from core.tools.manager import McpManager
from core.config import load_app_config, AppConfig
from core.task.types import (
    RunPolicy,
    TaskEvent,
    TaskEventKind,
    TaskResult,
    TaskStatus,
    TaskTurnState,
    TurnContext,
    TurnOutcome,
    TurnOutcomeKind,
)
from core.task.retry import ErrorKind, classify_error
from core.task.repetition import ToolRepetitionDetector
from core.task.executor import LLMExecutor
from core.task.tool_executor import ToolExecutor
from core.task.event_emitter import EventEmitter

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
    """Unified think-act tool loop coordinator.

    Orchestrates LLM calls, tool execution, and event streaming.
    Delegates to specialized executors for each responsibility.
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        mcp_manager: McpManager,
    ) -> None:
        self._client = client
        self._mcp_manager = mcp_manager
        self._llm_executor = LLMExecutor(client)
        self._tool_executor = ToolExecutor(mcp_manager)
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
        turn_context = TurnContext(turn=0)
        repetition_detector = ToolRepetitionDetector()
        emitter = EventEmitter(on_event)

        for turn in range(turns_limit):
            turn_context.turn = turn + 1
            outcome = await self._run_turn(
                provider=provider,
                conversation=conversation,
                policy=policy,
                turn_context=turn_context,
                repetition_detector=repetition_detector,
                emitter=emitter,
                turns_limit=turns_limit,
                on_token=on_token,
                on_thinking=on_thinking,
                approval_callback=approval_callback,
                cancel_event=cancel_event,
                debug_log_path=debug_log_path,
                on_event=on_event,
            )
            turn_context = outcome.context
            if outcome.final_message is not None:
                final_assistant = outcome.final_message

            if outcome.kind == TurnOutcomeKind.CONTINUE:
                continue
            if outcome.kind == TurnOutcomeKind.CANCELLED:
                return TaskResult(status=TaskStatus.CANCELLED, final_message=final_assistant)
            if outcome.kind == TurnOutcomeKind.FAILED:
                return TaskResult(status=TaskStatus.FAILED, final_message=final_assistant, error=outcome.error)
            return TaskResult(status=TaskStatus.COMPLETED, final_message=outcome.final_message or final_assistant)

        return TaskResult(status=TaskStatus.COMPLETED, final_message=final_assistant)

    async def _run_turn(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        turn_context: TurnContext,
        repetition_detector: ToolRepetitionDetector,
        emitter: EventEmitter,
        turns_limit: int,
        on_token,
        on_thinking,
        approval_callback,
        cancel_event,
        debug_log_path,
        on_event,
    ) -> TurnOutcome:
        if cancel_event and cancel_event.is_set():
            turn_context.state = TaskTurnState.CANCELLED
            return TurnOutcome(kind=TurnOutcomeKind.CANCELLED, context=turn_context)

        emitter.emit(TaskEventKind.TURN_START, turn=turn_context.turn, detail=f"Turn {turn_context.turn}/{turns_limit}")
        turn_context.state = TaskTurnState.PRE_TURN_HOOKS
        for hook in self._pre_turn_hooks:
            try:
                hook(conversation, turn_context.turn, policy)
            except Exception as he:
                logger.debug("Pre-turn hook error: %s", he)

        turn_context.state = TaskTurnState.CONDENSING
        await self._maybe_condense(conversation, provider, policy)

        assistant_msg = await self._request_assistant_message(
            provider=provider,
            conversation=conversation,
            policy=policy,
            turn_context=turn_context,
            emitter=emitter,
            on_token=on_token,
            on_thinking=on_thinking,
            cancel_event=cancel_event,
            debug_log_path=debug_log_path,
        )
        if isinstance(assistant_msg, TurnOutcome):
            return assistant_msg

        turn_context.runtime_messages = []
        turn_context.state = TaskTurnState.ASSISTANT_RECEIVED
        try:
            assistant_msg.seq_id = conversation.next_seq_id()
        except Exception as e:
            logger.warning("Failed to assign seq_id to assistant message: %s", e)

        emitter.emit(TaskEventKind.STEP, turn=turn_context.turn, data=assistant_msg)
        conversation.add_message(assistant_msg)

        for hook in self._post_turn_hooks:
            try:
                hook(conversation, turn_context.turn, assistant_msg)
            except Exception as he:
                logger.debug("Post-turn hook error: %s", he)

        if cancel_event and cancel_event.is_set():
            turn_context.state = TaskTurnState.CANCELLED
            return TurnOutcome(kind=TurnOutcomeKind.CANCELLED, context=turn_context, final_message=assistant_msg)

        if not assistant_msg.tool_calls:
            return await self._handle_turn_without_tools(
                provider=provider,
                conversation=conversation,
                policy=policy,
                turn_context=turn_context,
                assistant_msg=assistant_msg,
            )

        turn_context.nudge_count = 0
        turn_context.state = TaskTurnState.TOOL_EXECUTION
        return await self._execute_tool_calls(
            provider=provider,
            conversation=conversation,
            policy=policy,
            turn_context=turn_context,
            assistant_msg=assistant_msg,
            repetition_detector=repetition_detector,
            emitter=emitter,
            approval_callback=approval_callback,
            cancel_event=cancel_event,
            on_event=on_event,
            on_token=on_token,
            on_thinking=on_thinking,
        )

    async def _request_assistant_message(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        turn_context: TurnContext,
        emitter: EventEmitter,
        on_token,
        on_thinking,
        cancel_event,
        debug_log_path,
    ) -> Message | TurnOutcome:
        turn_context.state = TaskTurnState.LLM_CALL
        try:
            return await self._llm_executor.call_with_retry(
                provider=provider,
                conversation=conversation,
                policy=policy,
                runtime_messages=turn_context.runtime_messages,
                on_token=on_token,
                on_thinking=on_thinking,
                cancel_event=cancel_event,
                debug_log_path=debug_log_path,
                emit=lambda **kw: emitter.emit(turn=turn_context.turn, **kw),
            )
        except Exception as e:
            kind = classify_error(e)
            if kind == ErrorKind.CONTEXT_OVERFLOW:
                try:
                    await self._force_condense(conversation, provider, policy)
                    return await self._llm_executor._call_raw(
                        provider=provider,
                        conversation=conversation,
                        policy=policy,
                        runtime_messages=turn_context.runtime_messages,
                        on_token=on_token,
                        on_thinking=on_thinking,
                        cancel_event=cancel_event,
                        debug_log_path=debug_log_path,
                    )
                except Exception as e2:
                    turn_context.state = TaskTurnState.FAILED
                    return TurnOutcome(kind=TurnOutcomeKind.FAILED, context=turn_context, error=str(e2))
            turn_context.state = TaskTurnState.FAILED
            return TurnOutcome(kind=TurnOutcomeKind.FAILED, context=turn_context, error=str(e))

    async def _handle_turn_without_tools(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        turn_context: TurnContext,
        assistant_msg: Message,
    ) -> TurnOutcome:
        mode_slug = (policy.mode or "chat").lower()
        if mode_slug in _AUTO_CONTINUE_MODES and turn_context.nudge_count < _MAX_NUDGE_COUNT:
            turn_context.nudge_count += 1
            logger.info(
                "Auto-continue nudge %d/%d (mode=%s)",
                turn_context.nudge_count,
                _MAX_NUDGE_COUNT,
                mode_slug,
            )
            turn_context.runtime_messages = [Message(role="user", content=_NUDGE_TEXT)]
            turn_context.state = TaskTurnState.TURN_COMPLETE
            return TurnOutcome(kind=TurnOutcomeKind.CONTINUE, context=turn_context, final_message=assistant_msg)

        await self._maybe_condense(conversation, provider, policy)
        self._attach_state_snapshot(conversation, assistant_msg)
        turn_context.state = TaskTurnState.TURN_COMPLETE
        return TurnOutcome(kind=TurnOutcomeKind.COMPLETE, context=turn_context, final_message=assistant_msg)

    async def _execute_tool_calls(
        self,
        *,
        provider: Provider,
        conversation: Conversation,
        policy: RunPolicy,
        turn_context: TurnContext,
        assistant_msg: Message,
        repetition_detector: ToolRepetitionDetector,
        emitter: EventEmitter,
        approval_callback,
        cancel_event,
        on_event,
        on_token,
        on_thinking,
    ) -> TurnOutcome:
        for tool_call in assistant_msg.tool_calls or []:
            if cancel_event and cancel_event.is_set():
                turn_context.state = TaskTurnState.CANCELLED
                return TurnOutcome(kind=TurnOutcomeKind.CANCELLED, context=turn_context, final_message=assistant_msg)

            tool_name, args, tool_call_id = self._tool_executor.parse_tool_call(tool_call)
            if repetition_detector.record(tool_name, args if isinstance(args, dict) else {}):
                logger.warning("Tool repetition detected: %s", tool_name)
                turn_context.runtime_messages = [Message(role="user", content=_REPETITION_WARNING)]
                repetition_detector.reset()
                turn_context.state = TaskTurnState.TURN_COMPLETE
                return TurnOutcome(kind=TurnOutcomeKind.CONTINUE, context=turn_context, final_message=assistant_msg)

            allowed = self._tool_executor.is_tool_allowed(tool_name, policy)
            context = self._tool_executor.build_tool_context(
                conversation=conversation,
                provider=provider,
                approval_callback=approval_callback,
                llm_client=self._client,
            )
            result_text = await self._tool_executor.execute_tool(
                tool_name=tool_name,
                tool_args=args,
                allowed=allowed,
                policy=policy,
                context=context,
            )

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

            if (context.state or {}).get("_task_completed"):
                self._tool_executor.sync_state(conversation, context)
                tool_msg = Message(role="tool", content=str(result_text), tool_call_id=tool_call_id)
                try:
                    tool_msg.seq_id = conversation.next_seq_id()
                except Exception as e:
                    logger.warning("Failed to assign seq_id to completion tool message: %s", e)
                emitter.emit(TaskEventKind.STEP, turn=turn_context.turn, data=tool_msg)
                conversation.add_message(tool_msg)
                turn_context.state = TaskTurnState.TURN_COMPLETE
                return TurnOutcome(kind=TurnOutcomeKind.COMPLETE, context=turn_context, final_message=assistant_msg)

            self._tool_executor.sync_state(conversation, context)
            tool_msg = Message(role="tool", content=str(result_text), tool_call_id=tool_call_id)
            try:
                tool_msg.seq_id = conversation.next_seq_id()
            except Exception as e:
                logger.warning("Failed to assign seq_id to tool message: %s", e)
            try:
                tool_msg.metadata = tool_msg.metadata or {}
                tool_msg.metadata["name"] = tool_name
            except Exception as e:
                logger.debug("Failed to set tool metadata: %s", e)
            self._tool_executor.attach_state_snapshot(conversation, tool_msg)
            emitter.emit(TaskEventKind.STEP, turn=turn_context.turn, data=tool_msg)
            conversation.add_message(tool_msg)

        turn_context.state = TaskTurnState.TURN_COMPLETE
        turn_context.runtime_messages = []
        return TurnOutcome(kind=TurnOutcomeKind.CONTINUE, context=turn_context, final_message=assistant_msg)

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
            except Exception as e:
                logger.debug("Failed to inherit work_dir for subtask: %s", e)

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
    # Context management (condense)
    # ------------------------------------------------------------------

    async def _maybe_condense(
        self,
        conversation: Conversation,
        provider: Provider,
        policy: RunPolicy,
    ) -> None:
        """使用统一的 ContextManager 进行上下文压缩。"""
        try:
            cfg = load_app_config()
        except Exception as e:
            logger.debug("Failed to load app config, using defaults: %s", e)
            cfg = AppConfig()

        try:
            cfg_enabled = bool(getattr(getattr(cfg, "context", None), "agent_auto_compress_enabled", True))
        except Exception as e:
            logger.debug("Failed to read auto_compress_enabled config: %s", e)
            cfg_enabled = True

        if policy.auto_compress_enabled is False:
            return
        if not cfg_enabled:
            return

        from core.context.condenser import ContextCondenser, CondensePolicy
        from core.context.manager import ContextManager

        condenser = ContextCondenser(self._client)
        context_manager = ContextManager(
            condenser=condenser,
            policy=CondensePolicy(
                max_active_messages=20,
                token_threshold_ratio=0.7,
                keep_last_n=3,
            )
        )

        should_compress = context_manager._should_compress(
            conversation,
            int(policy.context_window_limit)
        )

        if should_compress:
            logger.info("触发上下文压缩")
            await condenser.auto_condense(
                conversation=conversation,
                provider=provider,
                context_window_limit=int(policy.context_window_limit),
                app_config=cfg,
                policy=context_manager.policy,
            )

    async def _force_condense(
        self,
        conversation: Conversation,
        provider: Provider,
        policy: RunPolicy,
    ) -> None:
        """Emergency condense on context overflow."""
        from core.context.condenser import ContextCondenser as Condenser
        condenser = Condenser(self._client)
        state = conversation.get_state()
        await condenser.condense_state(conversation, provider, state, keep_last_n=3)
        conversation.set_state(state)
        logger.info("Emergency condense complete")

    def _attach_state_snapshot(self, conversation: Conversation, msg: Message) -> None:
        """Attach state snapshot to message."""
        self._tool_executor.attach_state_snapshot(conversation, msg)
