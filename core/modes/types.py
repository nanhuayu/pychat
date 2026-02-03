from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union


ModeSource = Literal["global", "project", "builtin"]


@dataclass(frozen=True)
class PromptComponent:
    role_definition: Optional[str] = None
    when_to_use: Optional[str] = None
    description: Optional[str] = None
    custom_instructions: Optional[str] = None


@dataclass(frozen=True)
class GroupOptions:
    file_regex: Optional[str] = None
    description: Optional[str] = None


GroupName = str
GroupEntry = Union[GroupName, Tuple[GroupName, GroupOptions]]


@dataclass(frozen=True)
class ModeConfig:
    slug: str
    name: str
    role_definition: str
    when_to_use: Optional[str] = None
    description: Optional[str] = None
    custom_instructions: Optional[str] = None
    groups: Sequence[GroupEntry] = field(default_factory=tuple)
    source: Optional[ModeSource] = None

    def is_agent_like(self) -> bool:
        """Whether this mode should include tool/workspace framing in system prompt."""
        # Conservative heuristic: only treat as agent-like if it can *change* the system
        # (edit/command), or if it's explicitly a tool-execution mode.
        if self.slug in {"agent", "code", "debug"}:
            return True

        group_names: List[str] = []
        for g in self.groups or []:
            if isinstance(g, tuple) and g:
                group_names.append(str(g[0]))
            else:
                group_names.append(str(g))

        agent_groups = {"edit", "command"}
        return any((n in agent_groups) for n in group_names)


def normalize_mode_slug(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return "chat"

    # Legacy compatibility.
    if s in {"chat", "agent"}:
        return s

    return s


def safe_mode_display_name(mode: ModeConfig) -> str:
    return (mode.name or mode.slug or "mode").strip() or (mode.slug or "mode")
