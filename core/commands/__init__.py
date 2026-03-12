"""Command system.

Intercepts user input starting with ``/`` or ``#`` and routes registered
command names to command handlers. File mentions such as ``#src/main.py``
remain part of the inline mention system.

Extensible via ``~/.PyChat/commands/`` or ``.pychat/commands/``.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from core.commands.dispatcher import dispatch_command
from core.commands.parser import is_command_text, is_slash_command, parse_command_text
from core.commands.types import CommandAction, CommandResult, SlashCommand
from core.commands.mentions import (
    MentionCandidate,
    MentionKind,
    MentionQuery,
    MentionResolver,
    extract_mention_query,
)
from core.modes.manager import ModeManager

logger = logging.getLogger(__name__)


class CommandRegistry:
    """Registry of commands and inline mention providers."""

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

    def has(self, name: str) -> bool:
        return bool(name) and name in self._commands

    def is_command(self, text: str) -> bool:
        prefix, cmd_name, _args = parse_command_text(text)
        if not prefix or not cmd_name:
            return False
        return self.has(cmd_name)

    def is_slash_command(self, text: str) -> bool:
        return is_slash_command(text) and self.is_command(text)

    def parse(self, text: str) -> tuple[str, str]:
        """Parse command text → ``("command", "args")``."""
        _prefix, cmd_name, args = parse_command_text(text)
        return (cmd_name, args)

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
        """Execute a registered command and return a CommandResult."""
        try:
            return dispatch_command(text, commands=self._commands, context=context)
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
        from core.commands import handlers as h

        self.register(SlashCommand(
            name="help",
            description="Show available slash commands",
            handler=lambda args, ctx: h.cmd_help(args, ctx, list_commands=self.list_commands),
        ))
        self.register(SlashCommand(
            name="compact",
            description="Manually condense the conversation context",
            handler=h.cmd_compact,
        ))
        self.register(SlashCommand(
            name="mode",
            description="Switch conversation mode (e.g. /mode code)",
            handler=h.cmd_mode,
        ))
        self.register(SlashCommand(
            name="tools",
            description="List available tools for the current mode",
            handler=h.cmd_tools,
        ))
        self.register(SlashCommand(
            name="clear",
            description="Clear conversation history (keep system prompt)",
            handler=h.cmd_clear,
        ))
        self.register(SlashCommand(
            name="skill",
            description="Load a skill (e.g. /skill code-review) or list skills",
            handler=h.cmd_skill,
        ))
        self.register(SlashCommand(
            name="plan",
            description="View or update the session plan document",
            handler=h.cmd_plan,
        ))
        self.register(SlashCommand(
            name="memory",
            description="View or update the session memory document",
            handler=h.cmd_memory,
        ))
        self.register(SlashCommand(
            name="export",
            description="Export conversation (e.g. /export markdown)",
            handler=h.cmd_export,
            aliases=["save"],
        ))
