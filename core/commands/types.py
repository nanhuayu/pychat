"""Shared types for the command system."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Union


class CommandAction(str, Enum):
    """The type of action a command result triggers."""
    DISPLAY = "display"           # Show text to user in chat
    COMPACT = "compact"           # Trigger context condensation
    CLEAR = "clear"               # Clear conversation / new conversation
    MODE_SWITCH = "mode_switch"   # Switch mode (data = slug)
    SKILL = "skill"               # Activate skill (data = skill_name)
    EXPORT = "export"             # Export conversation (data = format)


@dataclass
class CommandResult:
    """Structured result from a slash command."""
    action: CommandAction = CommandAction.DISPLAY
    data: Any = None
    display_text: str = ""


@dataclass
class SlashCommand:
    """A single slash command definition."""

    name: str
    description: str
    handler: Callable[..., Union[str, CommandResult]]
    aliases: List[str] = field(default_factory=list)
