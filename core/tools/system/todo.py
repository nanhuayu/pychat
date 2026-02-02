
from typing import Dict, Any, List, Optional
import json
import re
import hashlib
from typing import Dict, Any, List
from core.tools.base import BaseTool, ToolContext, ToolResult

class TodoListTool(BaseTool):
    @property
    def name(self) -> str:
        return "update_todo_list"

    @property
    def description(self) -> str:
        return "Update the todo list for the current task using a Markdown-formatted checklist. This helps track progress."

    @property
    def category(self) -> str:
        return "misc"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "string",
                    "description": "Markdown formatted checklist (e.g. '- [ ] Task 1\\n- [x] Task 2')"
                }
            },
            "required": ["todos"]
        }

    def _parse_markdown_checklist(self, md: str) -> List[Dict[str, Any]]:
        if not md:
            return []
        
        lines = [l.strip() for l in md.splitlines() if l.strip()]
        todos = []
        
        for line in lines:
            # Match "- [x] content" or "[ ] content"
            match = re.match(r'^(?:-\s*)?\[\s*([ xX\-\~])\s*\]\s+(.+)$', line)
            if not match:
                continue
                
            mark = match.group(1)
            content = match.group(2)
            
            status = "pending"
            if mark.lower() == 'x':
                status = "completed"
            elif mark in ['-', '~']:
                status = "in_progress"
                
            # Generate stable ID based on content
            # (In a real app, we might want to preserve IDs if passed, but here we just parse text)
            item_id = hashlib.md5((content + status).encode('utf-8')).hexdigest()
            
            todos.append({
                "id": item_id,
                "content": content,
                "status": status
            })
            
        return todos

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        todos_raw = arguments.get("todos", "")
        
        # Parse markdown
        parsed_todos = self._parse_markdown_checklist(todos_raw)
        
        if not parsed_todos:
             return ToolResult("No valid todo items found in input. Use format '- [ ] Task name'", is_error=True)

        # In a real "Agent" system, we would update the Task state here.
        # context.state['todos'] = parsed_todos
        
        # Format back to Markdown for confirmation
        result_lines = []
        for t in parsed_todos:
            box = "[ ]"
            if t['status'] == 'completed':
                box = "[x]"
            elif t['status'] == 'in_progress':
                box = "[-]"
            result_lines.append(f"{box} {t['content']}")
            
        return ToolResult("Todo list updated:\n\n" + "\n".join(result_lines))
