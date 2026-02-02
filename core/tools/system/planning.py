import re
import hashlib
from typing import Any, Dict, List, Optional
from core.tools.base import BaseTool, ToolContext, ToolResult

class PlanTool(BaseTool):
    @property
    def name(self) -> str:
        return "builtin_plan" # Kept for compatibility, but logic is UpdateTodoList

    @property
    def description(self) -> str:
        return "Update the task plan (Todo List) using Markdown format."

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {"type": "string", "description": "Markdown checklist (e.g. '- [ ] Task 1')"},
            },
            "required": ["todos"],
            "additionalProperties": False,
        }

    def _parse_markdown_checklist(self, md: str) -> List[Dict[str, Any]]:
        if not isinstance(md, str):
            return []
        
        lines = [l.strip() for l in md.splitlines() if l.strip()]
        todos = []
        
        # Regex for '- [x] content' or '- [ ] content'
        # Roo Code: /^(?:-\s*)?\[\s*([ xX\-~])\s*\]\s+(.+)$/
        pattern = re.compile(r"^(?:-\s*)?\[\s*([ xX\-~])\s*\]\s+(.+)$")
        
        for line in lines:
            match = pattern.match(line)
            if not match:
                continue
            
            mark = match.group(1)
            content = match.group(2)
            
            status = "pending"
            if mark.lower() == "x":
                status = "completed"
            elif mark in ["-", "~"]:
                status = "in_progress"
                
            # Generate stable ID based on content
            # This is simplified compared to Roo Code's ID generation but sufficient
            item_id = hashlib.md5((content + status).encode("utf-8")).hexdigest()
            
            todos.append({
                "id": item_id,
                "content": content,
                "status": status
            })
            
        return todos

    def _todos_to_markdown(self, todos: List[Dict[str, Any]]) -> str:
        lines = []
        for t in todos:
            mark = " "
            if t["status"] == "completed":
                mark = "x"
            elif t["status"] == "in_progress":
                mark = "-"
            lines.append(f"- [{mark}] {t['content']}")
        return "\n".join(lines)

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        todos_raw = arguments.get("todos", "")
        
        if not todos_raw:
             return ToolResult("Missing 'todos' (markdown string)", is_error=True)

        parsed_todos = self._parse_markdown_checklist(todos_raw)
        
        if not parsed_todos:
             # Maybe user sent empty string or invalid format
             # Roo Code returns empty array if parsing fails but here we warn
             return ToolResult("No valid todo items found in input. Use format '- [ ] Task'", is_error=True)

        # Store in state
        # In Roo Code, they compare with 'approvedTodoList' and ask for approval if changed.
        # We will just update for now, relying on the Agent's own reasoning loop.
        
        # Retrieve previous state to check changes (optional, for logging)
        # prev_todos = context.state.get("plan", [])
        
        context.state["plan"] = parsed_todos
        
        formatted_md = self._todos_to_markdown(parsed_todos)
        return ToolResult(f"Plan updated:\n{formatted_md}")
