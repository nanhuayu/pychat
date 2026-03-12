import json
import re
import subprocess
import os
from typing import Any, Dict
from core.tools.base import BaseTool, ToolContext, ToolResult


def _decode_subprocess_output(data: object) -> str:
    if not data:
        return ""
    if isinstance(data, str):
        return data
    if not isinstance(data, (bytes, bytearray)):
        try:
            return str(data)
        except Exception:
            return ""

    raw = bytes(data)
    for enc in ("utf-8", "utf-8-sig", "gbk", "mbcs"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


# Commands that could cause irreversible damage — require explicit approval
_DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+-r\b",
    r"\bdel\s+/[sS]",
    r"\bformat\b",
    r"\bmkfs\b",
    r"\bdd\s+",
    r"\b>\s*/dev/",
    r"\bgit\s+push\s+.*--force",
    r"\bgit\s+reset\s+--hard",
    r"\bdrop\s+database\b",
    r"\bdrop\s+table\b",
    r"\btruncate\s+",
    r"\bshutdown\b",
    r"\breboot\b",
]

_MAX_OUTPUT_LINES = 2000
_MAX_OUTPUT_BYTES = 50 * 1024  # 50 KB


def _is_dangerous(command: str) -> bool:
    cmd_lower = command.lower()
    return any(re.search(p, cmd_lower) for p in _DANGEROUS_PATTERNS)


def _truncate_output(text: str) -> str:
    if len(text) > _MAX_OUTPUT_BYTES:
        text = text[:_MAX_OUTPUT_BYTES] + f"\n\n... [truncated at {_MAX_OUTPUT_BYTES} bytes]"
    lines = text.splitlines()
    if len(lines) > _MAX_OUTPUT_LINES:
        text = "\n".join(lines[:_MAX_OUTPUT_LINES]) + f"\n\n... [{len(lines) - _MAX_OUTPUT_LINES} lines truncated]"
    return text


class ExecuteCommandTool(BaseTool):
    def __init__(self):
        super().__init__()
        self._approved_commands = set()

    @property
    def name(self) -> str:
        return "execute_command"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the workspace. "
            "Supports timeout, background execution, and output truncation. "
            "Dangerous commands (rm -rf, git push --force, etc.) require explicit user approval."
        )

    @property
    def group(self) -> str:
        return "command"

    @property
    def category(self) -> str:
        return "command"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (default '.')"},
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default 120, max 600)",
                },
                "background": {
                    "type": "boolean",
                    "description": "Run in background (returns immediately, default false)",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        command = arguments.get("command", "")
        cwd_str = arguments.get("cwd", ".")
        timeout_sec = min(int(arguments.get("timeout", 120) or 120), 600)
        background = bool(arguments.get("background", False))

        if not command:
            return ToolResult("Missing 'command'", is_error=True)

        try:
            cwd_path = context.resolve_path(cwd_str)
        except Exception as e:
            return ToolResult(str(e), is_error=True)

        # Dangerous command gate — always require fresh approval
        dangerous = _is_dangerous(command)
        cmd_key = f"{command}@{cwd_path}"

        if dangerous:
            if not await context.ask_approval(
                f"⚠️ DANGEROUS command detected!\n> {command}\n\nThis may cause irreversible changes. Approve?"
            ):
                return ToolResult("User denied dangerous command execution", is_error=True)
        elif cmd_key not in self._approved_commands:
            if not await context.ask_approval(f"Execute shell command in {cwd_path}?\n> {command}"):
                return ToolResult("User denied execution", is_error=True)
            self._approved_commands.add(cmd_key)

        # Background execution
        if background:
            try:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=str(cwd_path),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return ToolResult(f"Command started in background (PID {proc.pid})")
            except Exception as e:
                return ToolResult(f"Failed to start background process: {e}", is_error=True)

        # Foreground execution with timeout
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd_path),
                capture_output=True,
                text=False,
                timeout=timeout_sec,
            )

            stdout = _truncate_output(_decode_subprocess_output(proc.stdout).strip())
            stderr = _truncate_output(_decode_subprocess_output(proc.stderr).strip())
            exit_code = proc.returncode

            output_parts = []
            output_parts.append(f"Command executed in '{cwd_path}'. Exit code: {exit_code}")

            if stdout:
                output_parts.append(f"Stdout:\n{stdout}")
            if stderr:
                output_parts.append(f"Stderr:\n{stderr}")

            return ToolResult("\n\n".join(output_parts))

        except subprocess.TimeoutExpired:
            return ToolResult(
                f"Command timed out after {timeout_sec}s. "
                f"Use 'background: true' for long-running commands.",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(f"Execution error: {e}", is_error=True)
