from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from models.conversation import Conversation
from models.provider import Provider
from core.llm.token_utils import estimate_conversation_tokens
from core.condense.condenser import ContextCondenser
from core.state.services.summary_service import SummaryService


@dataclass
class CompressionPolicy:
    """Policy for automatic conversation compression.

    This is intentionally simple and deterministic:
    - Per-message: summarize verbose tool outputs / long assistant messages into Message.summary
    - Global: archive older active messages into SessionState.summary via SummaryService (state-driven)
    """

    # Per-message condensation
    per_message_lookback: int = 20
    tool_min_chars: int = 200
    assistant_min_chars: int = 800

    # Global archive triggers
    max_active_messages: int = 20
    token_threshold_ratio: float = 0.7

    # Archive behavior
    keep_last_n: int = 10


class CompressionService:
    @staticmethod
    async def manage(
        *,
        conversation: Conversation,
        provider: Provider,
        llm_client: Any,
        context_window_limit: int,
        policy: Optional[CompressionPolicy] = None,
    ) -> None:
        """Auto-manage conversation compression.

        Mutates:
        - message.summary (per-message)
        - message.condense_parent (archive tagging)
        - conversation state (SessionState.summary + archived_summaries)
        """
        pol = policy or CompressionPolicy()

        # 1) Per-message condensation (cheap, frequent)
        condenser = ContextCondenser(llm_client)
        messages = conversation.messages

        start_idx = max(0, len(messages) - pol.per_message_lookback)
        end_idx = max(0, len(messages) - 1)

        for i in range(end_idx - 1, start_idx - 1, -1):
            msg = messages[i]
            if getattr(msg, "summary", None):
                continue

            should = False
            if msg.role == "tool":
                if (msg.content or "") and len(msg.content) > pol.tool_min_chars:
                    should = True
            elif msg.role == "assistant":
                if (msg.content or "") and len(msg.content) > pol.assistant_min_chars:
                    should = True

            if should:
                await condenser.condense_message(msg, provider)

        # 2) Global archive (expensive, rare)
        active_messages_count = len(
            [
                m
                for m in conversation.messages
                if not m.condense_parent and not m.truncation_parent and m.role != "system"
            ]
        )
        current_tokens = estimate_conversation_tokens(conversation)
        threshold = int(context_window_limit * float(pol.token_threshold_ratio))

        should_archive = (active_messages_count > pol.max_active_messages) or (current_tokens > threshold)
        if not should_archive:
            return

        state = conversation.get_state()
        feedback = await SummaryService.archive_context(
            state=state,
            llm_client=llm_client,
            conversation=conversation,
            provider=provider,
            current_seq=conversation.current_seq_id(),
            keep_last_n=pol.keep_last_n,
        )
        conversation.set_state(state)

        if feedback:
            print("[CompressionService] " + " | ".join(feedback))
