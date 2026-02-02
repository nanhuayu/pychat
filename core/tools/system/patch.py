import re
import os
from pathlib import Path
from typing import Any, Dict
from core.tools.base import BaseTool, ToolContext, ToolResult

class PatchTool(BaseTool):
    @property
    def name(self) -> str:
        return "builtin_apply_patch"

    @property
    def description(self) -> str:
        return "Apply a unified diff patch to a file. Supports fuzzy application."

    @property
    def category(self) -> str:
        return "edit"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path to patch"},
                "diff": {"type": "string", "description": "The unified diff content to apply"},
            },
            "required": ["path", "diff"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        path_str = arguments.get("path", "")
        diff = arguments.get("diff", "")
        
        if not path_str:
            return ToolResult("Missing 'path'", is_error=True)
        if not diff:
            return ToolResult("Missing 'diff'", is_error=True)

        try:
            file_path = context.resolve_path(path_str)
        except Exception as e:
            return ToolResult(str(e), is_error=True)

        if not file_path.exists():
            return ToolResult(f"File not found: {path_str}", is_error=True)

        # Critical: Ask approval
        if not await context.ask_approval(f"Apply patch to {file_path}?"):
            return ToolResult("User denied patch application", is_error=True)

        try:
            original_content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(f"Failed to read file: {e}", is_error=True)

        # Simple Python-based patch application (Hunk by Hunk)
        # This is a simplified implementation. For production, use a library or 'patch' command.
        
        try:
            new_content = self._apply_patch_string(original_content, diff)
            file_path.write_text(new_content, encoding="utf-8")
            return ToolResult(f"Successfully applied patch to {path_str}")
        except Exception as e:
            return ToolResult(f"Patch failed: {e}", is_error=True)

    def _apply_patch_string(self, original: str, diff: str) -> str:
        # A very basic unified diff applier
        # Parses @@ -O,L +N,M @@ headers
        
        lines = original.splitlines(keepends=True)
        # Ensure last line has newline for consistent processing if needed, 
        # but splitlines(keepends=True) usually preserves it.
        
        # Parse diff
        diff_lines = diff.splitlines(keepends=True)
        
        # Regex for hunk header
        hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
        
        # We need to apply hunks in reverse order to avoid offset issues?
        # Standard patch applies them in order but tracks offset.
        # Here we will try a simple approach: verify context and replace.
        
        # Actually, implementing a robust patcher in 50 lines is hard.
        # Strategy: Use 'git apply' if available (if in git repo).
        # Fallback: exact match search/replace for the "remove" block.
        
        # Let's try 'git apply' first if we are in a git repo?
        # But 'git apply' requires a file patch header usually.
        
        # Simplified logic:
        # 1. Identify chunks starting with @@
        # 2. For each chunk, identify "lines to remove" and "lines to add"
        # 3. Find "lines to remove" in original (handling context lines)
        # 4. Replace with "lines to add"
        
        # This effectively becomes multiple search-and-replaces.
        
        current_lines = list(lines)
        offset = 0 # Track line number shifts if we were doing line-index based.
        # But we will do string replacement on the whole content for simplicity if possible?
        # No, that's dangerous with duplicate content.
        
        # Better: Reconstruct the "search block" from the diff hunk (context + deletions)
        # and the "replace block" (context + additions).
        
        i = 0
        while i < len(diff_lines):
            line = diff_lines[i]
            match = hunk_re.match(line)
            if match:
                # Start of a hunk
                # Collect hunk lines until next hunk or end
                hunk_content = []
                i += 1
                while i < len(diff_lines) and not hunk_re.match(diff_lines[i]):
                    hunk_content.append(diff_lines[i])
                    i += 1
                
                # Process hunk
                search_block = []
                replace_block = []
                
                for hline in hunk_content:
                    if hline.startswith(' '):
                        # Context
                        search_block.append(hline[1:])
                        replace_block.append(hline[1:])
                    elif hline.startswith('-'):
                        # Delete
                        search_block.append(hline[1:])
                    elif hline.startswith('+'):
                        # Add
                        replace_block.append(hline[1:])
                    # Ignore others like '\ No newline...'
                
                # Now try to find search_block in current_lines
                # Convert list of lines to string
                search_str = "".join(search_block)
                replace_str = "".join(replace_block)
                
                # Find in original text
                # Note: This ignores line numbers in @@ header, treating it as search/replace
                # This is "fuzzy" enough for simple cases and robust against line shifts
                
                original_text = "".join(current_lines)
                if search_str not in original_text:
                    # Try whitespace loose match?
                    # For now, strict.
                    raise ValueError("Could not find context for hunk")
                
                # Replace only the first occurrence? Or use the line numbers hint?
                # Using line numbers is safer if provided.
                # But for this simple implementation, let's replace first occurrence 
                # (risk: if same code block appears twice).
                # To be safer, we should respect the approximate location.
                
                current_lines = original_text.replace(search_str, replace_str, 1).splitlines(keepends=True)
                
            else:
                i += 1
                
        return "".join(current_lines)
