"""Unified context condenser.

Merges ``core.condense.condenser.ContextCondenser`` and
``core.state.services.compression_service.CompressionService`` into a
single class with a clean ``auto_condense`` entry point that the Task
engine can call on every turn.

Main changes vs the old split design:
- ``auto_condense`` is the **only** public entry — it runs per-message
  condensation AND global archive in one pass.
- Token estimation is done locally (no circular deps).
- Summary prompts come from ``core.prompts.templates``.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional

from models.conversation import Conversation, Message
from models.provider import Provider
from models.state import SessionState
from core.llm.token_utils import estimate_conversation_tokens
from core.prompts.templates import SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy knobs
# ---------------------------------------------------------------------------

@dataclass
class CondensePolicy:
    # Per-message condensation
    per_message_lookback: int = 20
    tool_min_chars: int = 200
    assistant_min_chars: int = 800

    # Global archive triggers
    max_active_messages: int = 20
    token_threshold_ratio: float = 0.7

    # Archive behaviour
    keep_last_n: int = 10


# ---------------------------------------------------------------------------
# ContextCondenser
# ---------------------------------------------------------------------------

class ContextCondenser:
    """Unified condenser — per-message summaries + global archive."""

    def __init__(self, client: Any) -> None:
        self.client = client

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def auto_condense(
        self,
        *,
        conversation: Conversation,
        provider: Provider,
        context_window_limit: int,
        app_config: Any = None,
        policy: Optional[CondensePolicy] = None,
    ) -> None:
        """Run full condense pipeline: per-message + global archive."""
        pol = policy or self._policy_from_config(app_config)
        await self._per_message_condense(conversation, provider, pol)
        await self._maybe_archive(conversation, provider, context_window_limit, pol)

    async def condense_state(
        self,
        conversation: Conversation,
        provider: Provider,
        state: SessionState,
        keep_last_n: int = 5,
    ) -> bool:
        """Condense older messages into ``state.summary``.

        Non-destructive — tags condensed messages with ``condense_parent``.
        """
        messages = conversation.messages
        if not messages:
            return False

        active_indices = [
            i for i, m in enumerate(messages)
            if m.role != "system" and not m.condense_parent
        ]

        if len(active_indices) <= keep_last_n:
            return False

        indices_to_keep = set(active_indices[-keep_last_n:])

        # 保底: ensure at least 1 user message is kept
        kept_has_user = any(
            messages[i].role == "user" for i in indices_to_keep
        )
        if not kept_has_user:
            # Find the latest user message among active indices and force-keep it
            for i in reversed(active_indices):
                if messages[i].role == "user":
                    indices_to_keep.add(i)
                    break

        indices_to_summarize = [i for i in active_indices if i not in indices_to_keep]
        if not indices_to_summarize:
            return False

        start_idx = indices_to_summarize[0]
        end_idx = indices_to_summarize[-1] + 1
        messages_to_summarize = messages[start_idx:end_idx]

        logger.info("Condensing %d messages…", len(messages_to_summarize))

        include_tool_details = bool(
            (conversation.settings or {}).get("summary_include_tool_details", False)
        )
        transcript = self._build_transcript(
            messages_to_summarize, include_tool_details=include_tool_details
        )

        prompt = f"## Previous Summary\n{state.summary}\n\n## New Conversation Delta\n{transcript}\n"
        summary_model = (
            (conversation.settings or {}).get("summary_model")
            or conversation.model
            or provider.default_model
        )
        summary_system = (
            (conversation.settings or {}).get("summary_system_prompt")
            or SUMMARY_SYSTEM_PROMPT
        )

        summary_conv = Conversation(
            id="temp_condense",
            messages=[Message(role="user", content=prompt)],
            model=summary_model,
            mode="chat",
            settings={
                "stream": False,
                "system_prompt_override": str(summary_system).strip(),
            },
        )
        try:
            response = await self.client.send_message(
                provider, summary_conv,
                enable_thinking=False, enable_search=False, enable_mcp=False,
            )
            new_summary = response.content or "No summary generated."
            if state.summary:
                state.archived_summaries.append(state.summary)
            state.summary = new_summary

            condense_id = str(uuid.uuid4())
            for msg in messages_to_summarize:
                msg.condense_parent = condense_id

            logger.info("Condense complete. Archived summaries: %d", len(state.archived_summaries))
            return True
        except Exception as e:
            logger.error("Condense failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Per-message condensation
    # ------------------------------------------------------------------

    async def _per_message_condense(
        self,
        conversation: Conversation,
        provider: Provider,
        pol: CondensePolicy,
    ) -> None:
        messages = conversation.messages
        start = max(0, len(messages) - pol.per_message_lookback)
        end = max(0, len(messages) - 1)

        for i in range(end - 1, start - 1, -1):
            msg = messages[i]
            if getattr(msg, "summary", None):
                continue
            should = False
            if msg.role == "tool" and len(msg.content or "") > pol.tool_min_chars:
                should = True
            elif msg.role == "assistant" and len(msg.content or "") > pol.assistant_min_chars:
                should = True
            if should:
                await self._condense_message(msg, provider)

    async def _condense_message(self, message: Message, provider: Provider) -> bool:
        if not message.content or message.summary:
            return False
        if len(message.content) < 500:
            return False

        prompt = (
            "请为以下消息生成一个简洁的摘要，保留关键信息和重要细节。\n\n"
            f"原始消息：\n{message.content}\n\n"
            "要求：\n"
            "1. 摘要长度控制在原文的20%以内\n"
            "2. 保留关键事实、数据、结论\n"
            "3. 使用清晰的要点形式\n"
            "4. 如果有代码或技术细节，请保留重要部分\n"
        )
        summary_conv = Conversation(
            title="Message Condensation",
            messages=[Message(role="user", content=prompt)],
            settings={
                "stream": False,
                "system_prompt_override": "You are a concise summarizer. Summarize the given message. Do not call tools. Output text only.",
            },
        )
        try:
            resp = await self.client.send_message(
                provider, summary_conv,
                enable_thinking=False, enable_search=False, enable_mcp=False,
            )
            message.summary = resp.content
            logger.debug("Generated summary for seq_id=%s", getattr(message, "seq_id", "?"))
            return True
        except Exception as e:
            logger.warning("Failed to summarize message: %s", e)
            return False

    # ------------------------------------------------------------------
    # Global archive
    # ------------------------------------------------------------------

    async def _maybe_archive(
        self,
        conversation: Conversation,
        provider: Provider,
        context_window_limit: int,
        pol: CondensePolicy,
    ) -> None:
        active_count = len([
            m for m in conversation.messages
            if not m.condense_parent
            and not getattr(m, "truncation_parent", None)
            and m.role != "system"
        ])
        current_tokens = estimate_conversation_tokens(conversation)
        threshold = int(context_window_limit * pol.token_threshold_ratio)

        if active_count <= pol.max_active_messages and current_tokens <= threshold:
            return

        state = conversation.get_state()
        success = await self.condense_state(
            conversation, provider, state, keep_last_n=pol.keep_last_n
        )
        if success:
            conversation.set_state(state)

    # ------------------------------------------------------------------
    # Transcript builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_transcript(
        messages: List[Message],
        *,
        include_tool_details: bool = False,
    ) -> str:
        def _compact(s: str, limit: int = 240) -> str:
            s = (s or "").replace("\r", " ").replace("\n", " ").strip()
            while "  " in s:
                s = s.replace("  ", " ")
            return (s[:limit] + "...") if len(s) > limit else s

        blocks: List[str] = []
        for m in messages:
            if m.role in ("system", "tool"):
                continue
            role = (m.role or "").upper()
            content = m.summary if m.summary else m.content
            block = f"{role}:\n{content or ''}".strip()

            if m.role == "assistant" and m.tool_calls:
                tool_lines: List[str] = []
                for tc in m.tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    fn = (tc.get("function") or {}).get("name")
                    args = (tc.get("function") or {}).get("arguments")
                    result = tc.get("result")
                    if include_tool_details:
                        tool_lines.append(
                            f"- tool_call id={tc.get('id')} name={fn} "
                            f"args={_compact(str(args or ''))} "
                            f"result={_compact(str(result or ''))}"
                        )
                    else:
                        rs = _compact(str(result or ""))
                        if rs:
                            tool_lines.append(f"- tool_call name={fn} result={rs}")
                        else:
                            tool_lines.append(f"- tool_call name={fn}")
                if tool_lines:
                    block = f"{block}\n\nTOOL_CALLS:\n" + "\n".join(tool_lines)

            blocks.append(block)

        return "\n\n---\n\n".join(blocks).strip()

    # ------------------------------------------------------------------
    # Config → policy
    # ------------------------------------------------------------------

    @staticmethod
    def _policy_from_config(app_config: Any) -> CondensePolicy:
        pol = CondensePolicy()
        if app_config is None:
            return pol
        try:
            overrides = getattr(app_config, "compression_policy", None)
            if overrides:
                for field_name in ("per_message_lookback", "tool_min_chars",
                                   "assistant_min_chars", "max_active_messages",
                                   "token_threshold_ratio", "keep_last_n"):
                    val = getattr(overrides, field_name, None)
                    if val is not None:
                        setattr(pol, field_name, val)
        except Exception:
            pass
        return pol
