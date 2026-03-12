from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Union, Callable

class ToolResult:
    """Standardized result from a tool execution."""
    def __init__(self, content: Union[str, List[Dict[str, Any]]], is_error: bool = False):
        self.content = content
        self.is_error = is_error

    def to_string(self) -> str:
        if isinstance(self.content, str):
            return self.content
        # Handle list of content blocks (MCP style)
        text_parts = []
        for item in self.content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    text_parts.append(f"[Image: {item.get('mimeType')}]")
        return "\n".join(text_parts)

class ToolContext:
    """Context passed to tool execution."""
    def __init__(self, 
                 work_dir: str, 
                 approval_callback: Optional[Callable[[str], bool]] = None, 
                 state: Optional[Dict[str, Any]] = None,
                 llm_client: Any = None,
                 conversation: Any = None,
                 provider: Any = None):
        self.work_dir = work_dir
        self.approval_callback = approval_callback
        self.state = state if state is not None else {}
        self.llm_client = llm_client
        self.conversation = conversation
        self.provider = provider

    async def ask_approval(self, message: str) -> bool:
        if self.approval_callback:
            import inspect
            if inspect.iscoroutinefunction(self.approval_callback):
                return await self.approval_callback(message)
            result = self.approval_callback(message)
            if inspect.isawaitable(result):
                return await result
            return result
        return True # Default to auto-approve if no callback provided (for now, or False for security)

    def resolve_path(self, path: str) -> Any: # Returns Path object
        from pathlib import Path
        import os
        
        p = (path or ".").strip() or "."
        root = Path(self.work_dir).resolve()
        candidate = (root / p).resolve() if not os.path.isabs(p) else Path(p).resolve()
        
        # Security check: ensure path is within workspace
        # For now, strict check
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError(f"Access denied: Path '{path}' is outside workspace '{self.work_dir}'")
            
        return candidate

class BaseTool(ABC):
    """Abstract base class for all tools (System & MCP).

    Each tool declares:
    - ``group``: which tool-group it belongs to (maps to mode.groups).
      One of ``"read"``, ``"edit"``, ``"command"``, ``"search"``,
      ``"browser"``, ``"mcp"``, ``"modes"``.
    - ``category``: permission category (``"read"``/``"edit"``/``"command"``/``"misc"``).
    """

    # Max output chars before truncation (0 = no limit)
    max_output_chars: int = 60_000

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    def group(self) -> str:
        """Tool group for mode-based filtering.

        Override in subclasses. Defaults to same as ``category``.
        """
        return self.category

    @property
    def category(self) -> str:
        """Permission category: 'read', 'edit', 'command', 'misc'."""
        return "misc"

    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        """JSON Schema for input parameters."""
        pass

    @abstractmethod
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute the tool logic."""
        pass

    def truncate_output(self, text: str) -> str:
        """Truncate tool output if it exceeds max_output_chars."""
        if self.max_output_chars <= 0 or len(text) <= self.max_output_chars:
            return text
        half = self.max_output_chars // 2
        return (
            text[:half]
            + f"\n\n... [truncated {len(text) - self.max_output_chars} chars] ...\n\n"
            + text[-half:]
        )

    def to_openai_tool(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema
            }
        }
