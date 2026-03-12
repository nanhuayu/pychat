"""Slash command system.

Intercepts user input starting with ``/`` and routes to registered
command handlers.  Built-in commands: ``/compact``, ``/mode``,
``/tools``, ``/help``, ``/clear``.

Extensible via ``~/.PyChat/commands/`` or ``.pychat/commands/``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from core.commands.mentions import (
    MentionCandidate,
    MentionKind,
    MentionQuery,
    MentionResolver,
    extract_mention_query,
)
from core.modes.manager import ModeManager

logger = logging.getLogger(__name__)


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


class CommandRegistry:
    """Registry of slash commands and inline mention providers."""

    def __init__(self) -> None:
        self._commands: Dict[str, SlashCommand] = {}
        self._mention_triggers: Dict[str, Callable[[MentionQuery, Dict[str, Any]], List[MentionCandidate]]] = {
            "#": self._resolve_file_mentions,
            "@": self._resolve_symbol_mentions,
        }
        self._register_builtins()

    def register(self, cmd: SlashCommand) -> None:
        self._commands[cmd.name] = cmd
        for alias in cmd.aliases:
            self._commands[alias] = cmd

    def get(self, name: str) -> Optional[SlashCommand]:
        return self._commands.get(name)

    def list_commands(self) -> List[SlashCommand]:
        seen = set()
        result = []
        for cmd in self._commands.values():
            if id(cmd) not in seen:
                seen.add(id(cmd))
                result.append(cmd)
        return result

    def is_slash_command(self, text: str) -> bool:
        return bool(text and text.strip().startswith("/"))

    def parse(self, text: str) -> tuple[str, str]:
        """Parse ``/command args`` → ``("command", "args")``."""
        stripped = text.strip()
        if not stripped.startswith("/"):
            return ("", stripped)
        parts = stripped[1:].split(None, 1)
        cmd_name = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        return (cmd_name.lower(), args.strip())

    def get_mention_candidates(
        self,
        text: str,
        cursor_pos: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[tuple[MentionQuery, List[MentionCandidate]]]:
        """Resolve inline mention candidates for the cursor location."""
        query = extract_mention_query(text, cursor_pos, triggers=self._mention_triggers.keys())
        if not query:
            return None
        resolver = self._mention_triggers.get(query.trigger)
        if resolver is None:
            return None
        candidates = resolver(query, context or {})
        if not candidates:
            return None
        return query, candidates

    def resolve_mention_candidate(
        self,
        candidate: MentionCandidate,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Resolve a selected mention candidate into its backing value."""
        ctx = context or {}
        if candidate.kind == MentionKind.FILE:
            work_dir = str(ctx.get("work_dir") or "")
            if not work_dir:
                return None
            return MentionResolver(work_dir).resolve(candidate)
        return candidate.value

    def execute(self, text: str, context: Optional[Dict[str, Any]] = None) -> Optional[CommandResult]:
        """Execute a slash command and return a CommandResult (or None if not found)."""
        cmd_name, args = self.parse(text)
        cmd = self.get(cmd_name)
        if not cmd:
            return None
        try:
            raw = cmd.handler(args, context or {})
            # Normalize legacy string returns to CommandResult
            if isinstance(raw, CommandResult):
                return raw
            if isinstance(raw, str):
                return CommandResult(action=CommandAction.DISPLAY, display_text=raw)
            return CommandResult(action=CommandAction.DISPLAY, display_text=str(raw))
        except Exception as e:
            return CommandResult(action=CommandAction.DISPLAY, display_text=f"Command error: {e}")

    def _resolve_file_mentions(
        self,
        query: MentionQuery,
        ctx: Dict[str, Any],
    ) -> List[MentionCandidate]:
        work_dir = str(ctx.get("work_dir") or "")
        if not work_dir:
            return []
        return MentionResolver(work_dir).search(query.prefix)

    def _resolve_symbol_mentions(
        self,
        query: MentionQuery,
        ctx: Dict[str, Any],
    ) -> List[MentionCandidate]:
        raw_prefix = (query.prefix or "").strip()
        lowered = raw_prefix.lower()

        namespace = ""
        name_filter = lowered
        if ":" in lowered:
            namespace, _, name_filter = lowered.partition(":")

        candidates: list[MentionCandidate] = []
        if namespace in ("", "tool"):
            candidates.extend(self._resolve_tool_mentions(name_filter, ctx))
        if namespace in ("", "mode"):
            candidates.extend(self._resolve_mode_mentions(name_filter, ctx))
        return candidates[:30]

    def _resolve_tool_mentions(self, name_filter: str, ctx: Dict[str, Any]) -> List[MentionCandidate]:
        tools = ctx.get("available_tools", []) or []
        candidates: list[MentionCandidate] = []
        seen: set[str] = set()

        for tool in tools:
            fn = tool.get("function", {}) if isinstance(tool, dict) else {}
            name = str(fn.get("name") or "").strip()
            if not name or name in seen:
                continue
            haystack = f"tool:{name}".lower()
            if name_filter and name_filter not in haystack and name_filter not in name.lower():
                continue
            seen.add(name)
            candidates.append(
                MentionCandidate(
                    label=f"tool:{name}",
                    value=name,
                    kind=MentionKind.TOOL,
                    insert_text=f"@tool:{name}",
                )
            )
        return candidates

    def _resolve_mode_mentions(self, name_filter: str, ctx: Dict[str, Any]) -> List[MentionCandidate]:
        modes = ctx.get("available_modes")
        if not isinstance(modes, list):
            try:
                modes = [
                    {"slug": mode.slug, "name": mode.name}
                    for mode in ModeManager(None).list_modes()
                ]
            except Exception:
                modes = []

        candidates: list[MentionCandidate] = []
        seen: set[str] = set()
        for mode in modes:
            if not isinstance(mode, dict):
                continue
            slug = str(mode.get("slug") or "").strip()
            name = str(mode.get("name") or slug).strip()
            if not slug or slug in seen:
                continue
            haystack = f"mode:{slug} {name}".lower()
            if name_filter and name_filter not in haystack:
                continue
            seen.add(slug)
            label = f"mode:{slug}"
            if name and name.lower() != slug.lower():
                label = f"{label} - {name}"
            candidates.append(
                MentionCandidate(
                    label=label,
                    value=slug,
                    kind=MentionKind.MODE,
                    insert_text=f"@mode:{slug}",
                )
            )
        return candidates

    # ------------------------------------------------------------------
    # Built-in commands
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        self.register(SlashCommand(
            name="help",
            description="Show available slash commands",
            handler=self._cmd_help,
        ))
        self.register(SlashCommand(
            name="compact",
            description="Manually condense the conversation context",
            handler=self._cmd_compact,
        ))
        self.register(SlashCommand(
            name="mode",
            description="Switch conversation mode (e.g. /mode code)",
            handler=self._cmd_mode,
        ))
        self.register(SlashCommand(
            name="tools",
            description="List available tools for the current mode",
            handler=self._cmd_tools,
        ))
        self.register(SlashCommand(
            name="clear",
            description="Clear conversation history (keep system prompt)",
            handler=self._cmd_clear,
        ))
        self.register(SlashCommand(
            name="skill",
            description="Load a skill (e.g. /skill code-review) or list skills",
            handler=self._cmd_skill,
        ))
        self.register(SlashCommand(
            name="plan",
            description="View or update the session plan document",
            handler=self._cmd_plan,
        ))
        self.register(SlashCommand(
            name="memory",
            description="View or update the session memory document",
            handler=self._cmd_memory,
        ))
        self.register(SlashCommand(
            name="export",
            description="Export conversation (e.g. /export markdown)",
            handler=self._cmd_export,
            aliases=["save"],
        ))

    def _cmd_help(self, args: str, ctx: Dict[str, Any]) -> str:
        lines = ["**Available commands:**"]
        for cmd in self.list_commands():
            lines.append(f"  `/{cmd.name}` — {cmd.description}")
        return "\n".join(lines)

    def _cmd_compact(self, args: str, ctx: Dict[str, Any]) -> CommandResult:
        return CommandResult(action=CommandAction.COMPACT)

    def _cmd_mode(self, args: str, ctx: Dict[str, Any]) -> CommandResult:
        if not args.strip():
            current = ctx.get("current_mode", "chat")
            return CommandResult(
                action=CommandAction.DISPLAY,
                display_text=f"Current mode: **{current}**. Usage: `/mode <slug>` (e.g. `/mode code`)",
            )
        return CommandResult(action=CommandAction.MODE_SWITCH, data=args.strip())

    def _cmd_tools(self, args: str, ctx: Dict[str, Any]) -> str:
        tools = ctx.get("available_tools", [])
        if not tools:
            return "No tools available in current mode."
        lines = ["**Available tools:**"]
        for t in tools:
            fn = t.get("function", {})
            lines.append(f"  `{fn.get('name', '?')}` — {fn.get('description', '')[:80]}")
        return "\n".join(lines)

    def _cmd_clear(self, args: str, ctx: Dict[str, Any]) -> CommandResult:
        return CommandResult(action=CommandAction.CLEAR)

    def _cmd_skill(self, args: str, ctx: Dict[str, Any]) -> CommandResult:
        from core.skills import SkillsManager
        mgr = SkillsManager()
        if not args.strip():
            skills = mgr.list_skills()
            if not skills:
                return CommandResult(
                    action=CommandAction.DISPLAY,
                    display_text="No skills found. Add `.md` files to `~/.PyChat/skills/` or `.pychat/skills/`.",
                )
            lines = ["**Available skills:**"]
            for s in skills:
                tags = f" [{', '.join(s.tags)}]" if s.tags else ""
                lines.append(f"  `{s.name}`{tags} — {s.source}")
            return CommandResult(action=CommandAction.DISPLAY, display_text="\n".join(lines))
        name = args.strip().lower()
        skill = mgr.get(name)
        if not skill:
            return CommandResult(
                action=CommandAction.DISPLAY,
                display_text=f"Skill `{name}` not found. Use `/skill` to list available skills.",
            )
        return CommandResult(action=CommandAction.SKILL, data=name)

    def _cmd_plan(self, args: str, ctx: Dict[str, Any]) -> str:
        conv = ctx.get("conversation")
        if not conv:
            return "No active conversation."
        state = conv.get_state()
        doc = state.documents.get("plan")
        if args.strip():
            from models.state import SessionDocument
            state.documents["plan"] = SessionDocument(name="plan", content=args.strip())
            conv.set_state(state)
            return "Plan updated."
        if doc and doc.content:
            return f"**Session Plan:**\n{doc.content}"
        return "No plan set. Usage: `/plan <content>` to set one."

    def _cmd_memory(self, args: str, ctx: Dict[str, Any]) -> str:
        conv = ctx.get("conversation")
        if not conv:
            return "No active conversation."
        state = conv.get_state()
        if args.strip():
            # Parse "key=value" or just append to memory doc
            if "=" in args:
                key, _, value = args.partition("=")
                state.memory[key.strip()] = value.strip()
                conv.set_state(state)
                return f"Memory '{key.strip()}' saved."
            else:
                from models.state import SessionDocument
                doc = state.documents.get("memory")
                if doc:
                    doc.content += "\n" + args.strip()
                else:
                    state.documents["memory"] = SessionDocument(name="memory", content=args.strip())
                conv.set_state(state)
                return "Memory appended."
        # Show current memory
        lines = []
        if state.memory:
            lines.append("**Key-Value Memory:**")
            for k, v in state.memory.items():
                lines.append(f"  - **{k}**: {v}")
        doc = state.documents.get("memory")
        if doc and doc.content:
            lines.append(f"\n**Memory Document:**\n{doc.content}")
        if not lines:
            return "No memory stored. Usage: `/memory key=value` or `/memory <text>`"
        return "\n".join(lines)

    def _cmd_export(self, args: str, ctx: Dict[str, Any]) -> CommandResult:
        fmt = args.strip() or "markdown"
        return CommandResult(action=CommandAction.EXPORT, data=fmt)
