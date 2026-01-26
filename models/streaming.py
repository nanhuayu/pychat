"""Streaming runtime state models.

These are UI/runtime-only helpers (not persisted).
Keeping them in models/ makes them easy to import from UI and services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import threading


@dataclass
class ConversationStreamState:
    """Per-conversation in-flight streaming state."""

    conversation_id: str
    request_id: str
    model: str = ""
    visible_text: str = ""
    thinking_text: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        try:
            self.cancel_event.set()
        except Exception:
            pass
