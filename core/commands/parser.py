"""Command parsing helpers for both ``/`` and ``#`` prefixes."""
from __future__ import annotations


COMMAND_PREFIXES = ("/", "#")


def get_command_prefix(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith(COMMAND_PREFIXES):
        return stripped[0]
    return ""


def is_command_text(text: str) -> bool:
    return bool(get_command_prefix(text))


def parse_command_text(text: str) -> tuple[str, str, str]:
    """Parse ``/command args`` or ``#command args`` → ``(prefix, command, args)``."""
    stripped = text.strip()
    prefix = get_command_prefix(stripped)
    if not prefix:
        return ("", "", stripped)
    parts = stripped[1:].split(None, 1)
    cmd_name = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    return (prefix, cmd_name.lower(), args.strip())


def parse_slash_command(text: str) -> tuple[str, str]:
    """Backward-compatible slash parser wrapper."""
    _prefix, cmd_name, args = parse_command_text(text)
    return (cmd_name, args)


def is_slash_command(text: str) -> bool:
    return get_command_prefix(text) == "/"