import json
import subprocess
import os
from typing import Any, Dict
from core.tools.base import BaseTool, ToolContext, ToolResult

class ExecuteCommandTool(BaseTool):
    def __init__(self):
        super().__init__()
        self._approved_commands = set()

    @property
    def name(self) -> str:
        return "execute_command"

    @property
    def description(self) -> str:
        return "Execute a shell command in the workspace."

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
                # "timeoutSec": {"type": "number", "description": "Timeout in seconds (default 60)"}, # Optional, not in Roo Code core params usually
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        command = arguments.get("command", "")
        cwd_str = arguments.get("cwd", ".")
        
        if not command:
            return ToolResult("Missing 'command'", is_error=True)

        try:
            cwd_path = context.resolve_path(cwd_str)
        except Exception as e:
            return ToolResult(str(e), is_error=True)

        # Critical approval with deduplication
        # If command was already approved in this session, skip approval
        cmd_key = f"{command}@{cwd_path}"
        if cmd_key not in self._approved_commands:
            if not await context.ask_approval(f"Execute shell command in {cwd_path}?\n> {command}"):
                return ToolResult("User denied execution", is_error=True)
            self._approved_commands.add(cmd_key)

        try:
            # Use shell=True for flexibility
            # TODO: Implement persistent shell session if possible
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                timeout=120 # Default timeout
            )
            
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            exit_code = proc.returncode
            
            output_parts = []
            output_parts.append(f"Command executed in '{cwd_path}'. Exit code: {exit_code}")
            
            if stdout:
                output_parts.append(f"Stdout:\n{stdout}")
            if stderr:
                output_parts.append(f"Stderr:\n{stderr}")
                
            return ToolResult("\n\n".join(output_parts))
            
        except subprocess.TimeoutExpired:
            return ToolResult(f"Command timed out", is_error=True)
        except Exception as e:
            return ToolResult(f"Execution error: {e}", is_error=True)
