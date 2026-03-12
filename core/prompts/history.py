from __future__ import annotations

from typing import List

from models.conversation import Message


def get_effective_history(messages: List[Message]) -> List[Message]:
    """Return messages suitable for sending to the LLM.

    - Filters out condensed/truncated messages.
    - Preserves system messages.
    - Sanitizes orphan tool messages (tool without preceding assistant).
    - **Guarantees** at least 1 user message survives (保底).
    """
    effective: List[Message] = []
    for msg in messages:
        if msg.role == "system":
            effective.append(msg)
            continue
        if msg.condense_parent or msg.truncation_parent:
            continue

        if msg.role == "tool":
            prev = effective[-1] if effective else None
            if not prev or prev.role != "assistant":
                effective.append(
                    Message(
                        role="user",
                        content=f"Tool Output (Context Lost):\n{msg.content}",
                        tool_call_id=msg.tool_call_id,
                    )
                )
                continue

        effective.append(msg)

    # 保底: if no user messages survived, force-keep the latest user message
    has_user = any(m.role == "user" for m in effective)
    if not has_user:
        # Scan original messages in reverse to find the latest user message
        for msg in reversed(messages):
            if msg.role == "user":
                effective.append(msg)
                break

    return effective


def apply_context_window(messages: List[Message], max_messages: int) -> List[Message]:
    """Keep only the last N messages, while preserving system messages.
    
    Guarantees at least 1 user message in the result.
    """
    if not isinstance(max_messages, int) or max_messages <= 0:
        return messages
    if len(messages) <= max_messages:
        return messages

    pinned: List[Message] = [m for m in messages if m.role == "system"]
    rest: List[Message] = [m for m in messages if m.role != "system"]

    budget = max_messages - len(pinned)
    if budget <= 0:
        return pinned[:max_messages]

    tail = rest[-budget:]
    while tail and tail[0].role == "tool":
        tail = tail[1:]

    # 保底: ensure at least 1 user message
    if not any(m.role == "user" for m in tail):
        for msg in reversed(rest):
            if msg.role == "user":
                tail.insert(0, msg)
                break

    return pinned + tail
