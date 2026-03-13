"""Built-in command handlers.

Extracted from ``CommandRegistry`` to keep it focused on
registration / lookup / dispatch.
"""
from __future__ import annotations

from typing import Any, Dict

from core.commands.types import CommandAction, CommandResult


def cmd_help(args: str, ctx: Dict[str, Any], *, list_commands) -> str:
    """Show available commands."""
    lines = ["**Available commands** (`/` and `#` both supported):"]
    for cmd in list_commands():
        lines.append(f"  `/{cmd.name}` / `#{cmd.name}` — {cmd.description}")
    return "\n".join(lines)


def cmd_compact(args: str, ctx: Dict[str, Any]) -> CommandResult:
    return CommandResult(action=CommandAction.COMPACT)


def cmd_mode(args: str, ctx: Dict[str, Any]) -> CommandResult:
    if not args.strip():
        current = ctx.get("current_mode", "chat")
        return CommandResult(
            action=CommandAction.DISPLAY,
            display_text=f"Current mode: **{current}**. Usage: `/mode <slug>`, `#mode <slug>`, or `@mode:<slug>` (e.g. `@mode:code`).",
        )
    return CommandResult(action=CommandAction.MODE_SWITCH, data=args.strip())


def cmd_tools(args: str, ctx: Dict[str, Any]) -> str:
    tools = ctx.get("available_tools", [])
    if not tools:
        return "No tools available in current mode."
    lines = ["**Available tools:**"]
    for t in tools:
        fn = t.get("function", {})
        lines.append(f"  `{fn.get('name', '?')}` — {fn.get('description', '')[:80]}")
    return "\n".join(lines)


def cmd_clear(args: str, ctx: Dict[str, Any]) -> CommandResult:
    return CommandResult(action=CommandAction.CLEAR)


def cmd_skill(args: str, ctx: Dict[str, Any]) -> CommandResult:
    from core.skills import SkillsManager
    mgr = SkillsManager(str(ctx.get("work_dir") or "."))
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
            display_text=f"Skill `{name}` not found. Use `/skill` or `#skill` to list available skills.",
        )
    return CommandResult(action=CommandAction.SKILL, data=name)


def cmd_plan(args: str, ctx: Dict[str, Any]) -> str:
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


def cmd_memory(args: str, ctx: Dict[str, Any]) -> str:
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


def cmd_export(args: str, ctx: Dict[str, Any]) -> CommandResult:
    fmt = args.strip() or "markdown"
    return CommandResult(action=CommandAction.EXPORT, data=fmt)
