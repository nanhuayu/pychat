import json
import subprocess
import sys
from typing import Any, Dict

from core.tools.base import BaseTool, ToolContext, ToolResult

class PythonExecTool(BaseTool):
    @property
    def name(self) -> str:
        return "builtin_python_exec"

    @property
    def description(self) -> str:
        return "Execute Python code locally (no sandbox). Returns stdout/stderr."

    @property
    def category(self) -> str:
        return "command"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "timeoutSec": {"type": "number", "description": "Timeout seconds (default: 10)"},
                "cwd": {"type": "string", "description": "Workspace-relative working directory (default: '.')"},
            },
            "required": ["code"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        code = arguments.get("code", "")
        timeout_sec = float(arguments.get("timeoutSec", 30) or 30)
        cwd_str = arguments.get("cwd", ".")
        
        if not code or not code.strip():
            return ToolResult("Missing 'code'", is_error=True)
            
        timeout_sec = max(1.0, min(timeout_sec, 60.0))
        
        try:
            cwd_path = context.resolve_path(cwd_str)
        except Exception as e:
            return ToolResult(f"Invalid cwd: {e}", is_error=True)

        # Ask for approval (Critical for exec)
        approved = await context.ask_approval(f"Execute Python code in {cwd_path}?\nCode preview:\n{code[:100]}...")
        if not approved:
            return ToolResult("User denied execution", is_error=True)

        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=str(cwd_path),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            return ToolResult(json.dumps(
                {
                    "exitCode": proc.returncode,
                    "stdout": (proc.stdout or "").strip(),
                    "stderr": (proc.stderr or "").strip(),
                },
                ensure_ascii=False,
                indent=2,
            ))
        except subprocess.TimeoutExpired:
            return ToolResult(f"Python execution timed out after {timeout_sec:.0f}s", is_error=True)
        except Exception as e:
            return ToolResult(f"Python execution error: {e}", is_error=True)
