"""Inject structured context into user messages.

Follows the vscode agent pattern: environment/workspace/conversation-summary
are wrapped in XML tags and prepended to the **first user message** (or to
each user message, configurable).

This replaces the old approach of embedding environment info in the system
prompt — moving it to user messages keeps the system prompt focused on role
definition and rules, while giving the LLM concrete workspace awareness.
"""
from __future__ import annotations

import os
import platform
from typing import Any, Dict, List, Optional

from models.conversation import Conversation, Message
from utils.file_context import get_file_tree


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_environment_info() -> str:
    """OS / shell / date — always available."""
    os_name = platform.system()
    os_release = platform.release()
    shell = os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown"
    cwd = os.getcwd()
    lines = [
        f"<environment_info>",
        f"OS: {os_name} {os_release}",
        f"Shell: {shell}",
        f"CWD: {cwd}",
        f"</environment_info>",
    ]
    return "\n".join(lines)


def build_workspace_info(work_dir: str, *, max_depth: int = 2) -> str:
    """File tree of the workspace — may be empty for non-project chats."""
    abs_dir = os.path.abspath(work_dir)
    tree = get_file_tree(abs_dir, max_depth=max_depth)
    if not tree or not tree.strip():
        return ""
    return f"<workspace_info>\n{tree.strip()}\n</workspace_info>"


def build_conversation_summary(conversation: Conversation) -> str:
    """Condensed summary from SessionState, if any."""
    try:
        state = conversation.get_state()
        summary = getattr(state, "summary", "") or ""
        if not summary.strip():
            return ""
        return f"<conversation_summary>\n{summary.strip()}\n</conversation_summary>"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inject_user_context(
    conversation: Conversation,
    *,
    include_environment: bool = True,
    include_workspace: bool = True,
    include_summary: bool = True,
    inject_mode: str = "first",
) -> None:
    """Inject XML context sections into user message(s) **in-place**.

    Parameters
    ----------
    inject_mode
        ``"first"`` — inject into the first user message only.
        ``"latest"`` — inject into the last user message only.
        ``"all"`` — inject into every user message (not recommended).
    """
    work_dir = getattr(conversation, "work_dir", None) or "."

    sections: List[str] = []
    if include_environment:
        sections.append(build_environment_info())
    if include_workspace:
        ws = build_workspace_info(work_dir)
        if ws:
            sections.append(ws)
    if include_summary:
        cs = build_conversation_summary(conversation)
        if cs:
            sections.append(cs)

    if not sections:
        return

    context_block = "\n".join(sections)

    messages = conversation.messages or []

    if inject_mode == "first":
        for msg in messages:
            if msg.role == "user" and not _already_injected(msg):
                _prepend_context(msg, context_block)
                break
    elif inject_mode == "latest":
        for msg in reversed(messages):
            if msg.role == "user" and not _already_injected(msg):
                _prepend_context(msg, context_block)
                break
    elif inject_mode == "all":
        for msg in messages:
            if msg.role == "user" and not _already_injected(msg):
                _prepend_context(msg, context_block)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MARKER = "<environment_info>"


def _already_injected(msg: Message) -> bool:
    return bool(msg.content and _MARKER in msg.content)


def _prepend_context(msg: Message, block: str) -> None:
    original = (msg.content or "").strip()
    msg.content = f"{block}\n<user_request>\n{original}\n</user_request>"
