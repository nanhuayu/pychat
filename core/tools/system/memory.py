from typing import Any, Dict
from core.tools.base import BaseTool, ToolContext, ToolResult

class MemoryTool(BaseTool):
    @property
    def name(self) -> str:
        return "builtin_memory"

    @property
    def description(self) -> str:
        return "Store and retrieve key-value memory for the current agent session."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["set", "get", "forget", "list"], "description": "Action to perform"},
                "key": {"type": "string", "description": "Key for the memory item"},
                "value": {"type": "string", "description": "Value to store (for 'set')"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments.get("action")
        key = arguments.get("key")
        value = arguments.get("value")

        # Access shared state from context
        if "memory" not in context.state:
            context.state["memory"] = {}
        
        mem = context.state["memory"]

        if action == "set":
            if not key:
                return ToolResult("Missing 'key'", is_error=True)
            mem[key] = value
            return ToolResult(f"Memory stored: {key}")

        elif action == "get":
            if not key:
                return ToolResult("Missing 'key'", is_error=True)
            val = mem.get(key)
            if val is None:
                return ToolResult(f"Key '{key}' not found", is_error=True)
            return ToolResult(str(val))

        elif action == "forget":
            if not key:
                return ToolResult("Missing 'key'", is_error=True)
            if key in mem:
                del mem[key]
                return ToolResult(f"Memory forgotten: {key}")
            return ToolResult(f"Key '{key}' not found", is_error=True)

        elif action == "list":
            return ToolResult("\n".join([f"{k}: {v}" for k, v in mem.items()]) or "Memory is empty")

        return ToolResult(f"Unknown action: {action}", is_error=True)
