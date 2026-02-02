import json
import os
from typing import Any, Dict
from core.tools.base import BaseTool, ToolContext, ToolResult

class WriteToFileTool(BaseTool):
    @property
    def name(self) -> str:
        return "write_to_file"

    @property
    def description(self) -> str:
        return "Write content to a file. Overwrites existing files."

    @property
    def category(self) -> str:
        return "edit"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        path_str = arguments.get("path", "")
        content = arguments.get("content", "")
        
        if not path_str:
            return ToolResult("Missing 'path'", is_error=True)

        try:
            file_path = context.resolve_path(path_str)
        except Exception as e:
            return ToolResult(str(e), is_error=True)

        # Critical: Ask approval
        if not await context.ask_approval(f"Write to file {file_path}?"):
            return ToolResult("User denied file write", is_error=True)

        try:
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(f"Successfully wrote to {path_str}")
        except Exception as e:
            return ToolResult(f"Write error: {e}", is_error=True)


import re

# ======================================================================================
# Roo Code inspired helpers for robust file editing
# ======================================================================================

def count_occurrences(text: str, substring: str) -> int:
    if not substring:
        return 0
    return text.count(substring)

def normalize_to_lf(content: str) -> str:
    return content.replace("\r\n", "\n")

def build_whitespace_tolerant_regex(target: str) -> str:
    """
    Builds a regex that matches the target string but allows flexible whitespace.
    Adapted from Roo Code's EditFileTool.ts.
    """
    if not target:
        return ""
    
    # Split by whitespace sequences (keeping them)
    # \s matches [ \t\n\r\f\v], \S matches non-whitespace
    parts = re.findall(r'(\s+|\S+)', target)
    if not parts:
        return ""
    
    regex_parts = []
    for part in parts:
        if re.match(r'^\s+$', part):
            # If the whitespace run includes a newline, allow matching any whitespace (including newlines)
            # to tolerate wrapping changes across lines.
            if '\n' in part or '\r' in part:
                regex_parts.append(r'\s+')
            else:
                # Limit matching to horizontal whitespace so we don't accidentally consume
                # line breaks that precede indentation.
                regex_parts.append(r'[ \t]+')
        else:
            regex_parts.append(re.escape(part))
            
    return "".join(regex_parts)

class EditFileTool(BaseTool):
    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing a text segment with a new one. Supports whitespace-tolerant matching (Roo Code style)."

    @property
    def category(self) -> str:
        return "edit"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "old_str": {"type": "string", "description": "Text to find and replace (exact match or whitespace-tolerant)"},
                "new_str": {"type": "string", "description": "New text to insert"},
            },
            "required": ["path", "old_str", "new_str"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        path_str = arguments.get("path", "")
        old_str = arguments.get("old_str", "")
        new_str = arguments.get("new_str", "")

        if not path_str:
            return ToolResult("Missing 'path'", is_error=True)
        
        try:
            file_path = context.resolve_path(path_str)
        except Exception as e:
            return ToolResult(str(e), is_error=True)

        # Check file existence
        if not file_path.exists():
            if not old_str:
                # Creation mode
                if not await context.ask_approval(f"Create new file {file_path}?"):
                    return ToolResult("User denied file creation", is_error=True)
                try:
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(new_str, encoding="utf-8")
                    return ToolResult(f"Successfully created {path_str}")
                except Exception as e:
                    return ToolResult(f"Creation error: {e}", is_error=True)
            else:
                return ToolResult(f"File not found: {path_str}", is_error=True)
        
        # File exists
        if not old_str:
             return ToolResult("Missing 'old_str' for existing file. Use 'builtin_filesystem_write' to overwrite.", is_error=True)

        # Approval
        if not await context.ask_approval(f"Edit file {file_path}?"):
            return ToolResult("User denied file edit", is_error=True)

        try:
            content = file_path.read_text(encoding="utf-8")
            
            # 1. Try Exact Match
            if old_str in content:
                # Verify uniqueness if possible, but for now replace first occurrence
                count = content.count(old_str)
                if count > 1:
                     # Warn? Or just proceed? Roo Code warns.
                     pass 
                
                new_content = content.replace(old_str, new_str, 1)
                file_path.write_text(new_content, encoding="utf-8")
                return ToolResult(f"Successfully edited {path_str} (Exact match)")

            # 2. Try Whitespace-Tolerant Regex Match
            # Normalize to LF to ensure consistent regex behavior
            # content_lf = normalize_to_lf(content) 
            # old_str_lf = normalize_to_lf(old_str)
            # Actually, let's try to match against the raw content first with our smart regex
            
            regex_pattern = build_whitespace_tolerant_regex(old_str)
            if not regex_pattern:
                 return ToolResult("Could not build regex from old_str", is_error=True)
            
            # re.search allows us to find where it is
            match = re.search(regex_pattern, content)
            if not match:
                # Try normalizing both to LF and try again?
                # Sometimes CRLF issues cause mismatch even with \s+ if not handled carefully.
                # But \s matches \r and \n, so it should be fine.
                return ToolResult("Could not find old_str in file (tried exact and whitespace-tolerant match).", is_error=True)
            
            # Perform replacement
            # We use a lambda to replace with new_str but we need to be careful about regex groups in new_str if any.
            # new_str is a literal string, so we should escape it for re.sub if we use it as replacement pattern,
            # OR better: calculate the span and use string slicing to avoid regex replacement issues.
            
            span = match.span()
            new_content = content[:span[0]] + new_str + content[span[1]:]
            
            # Write back
            file_path.write_text(new_content, encoding="utf-8")
            return ToolResult(f"Successfully edited {path_str} (Regex match)")
            
        except Exception as e:
            return ToolResult(f"Edit error: {e}", is_error=True)



class DeleteFileTool(BaseTool):
    @property
    def name(self) -> str:
        return "builtin_filesystem_delete"

    @property
    def description(self) -> str:
        return "Delete a file or directory."

    @property
    def category(self) -> str:
        return "edit"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path"},
                "recursive": {"type": "boolean", "description": "Delete directory recursively (default false)"},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        path_str = arguments.get("path", "")
        recursive = bool(arguments.get("recursive", False))

        if not path_str:
            return ToolResult("Missing 'path'", is_error=True)

        try:
            file_path = context.resolve_path(path_str)
        except Exception as e:
            return ToolResult(str(e), is_error=True)

        if not file_path.exists():
            return ToolResult(f"Path not found: {path_str}", is_error=True)

        if not await context.ask_approval(f"DELETE {file_path}?"):
            return ToolResult("User denied deletion", is_error=True)

        try:
            if file_path.is_dir():
                if not recursive and any(file_path.iterdir()):
                    return ToolResult("Directory not empty. Use recursive=true to delete.", is_error=True)
                import shutil
                shutil.rmtree(file_path)
            else:
                file_path.unlink()
            return ToolResult(f"Successfully deleted {path_str}")
        except Exception as e:
            return ToolResult(f"Delete error: {e}", is_error=True)
