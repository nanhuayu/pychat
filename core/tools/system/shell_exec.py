import re
from typing import Any, Dict
from core.tools.base import BaseTool, ToolContext, ToolResult
from core.tools.process import CommandExecutionRequest, CommandExecutor, is_dangerous_command


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

class ExecuteCommandTool(BaseTool):
    def __init__(self):
        super().__init__()
        self._approved_commands = set()
        self._executor = CommandExecutor()

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
        dangerous = is_dangerous_command(command)
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
        try:
            result = self._executor.execute(
                CommandExecutionRequest(
                    command=command,
                    cwd=cwd_path,
                    timeout_sec=timeout_sec,
                    background=background,
                )
            )
            if result.timed_out:
                return ToolResult(
                    f"Command timed out after {timeout_sec}s. Use 'background: true' for long-running commands.",
                    is_error=True,
                )
            return ToolResult(result.to_display_text(cwd_path))
        except Exception as e:
            return ToolResult(f"Execution error: {e}", is_error=True)
