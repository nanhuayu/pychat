from typing import Dict, List, Any, Optional, Callable
import asyncio
from core.tools.base import BaseTool, ToolContext, ToolResult

class ToolRegistry:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ToolRegistry, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
        self._tools: Dict[str, BaseTool] = {}
        self._permissions_config: Dict[str, Any] = {
            "auto_approve_read": True,
            "auto_approve_edit": False,
            "auto_approve_command": False
        }
        self.initialized = True

    def register(self, tool: BaseTool):
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get OpenAI-compatible schemas for all registered tools."""
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def update_permissions(self, config: Dict[str, Any]):
        """Update permission settings."""
        self._permissions_config.update({
            k: v for k, v in config.items() 
            if k in self._permissions_config
        })

    async def execute(self, tool_name: str, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute a tool with permission checking."""
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(f"Tool '{tool_name}' not found", is_error=True)

        # Permission Wrapper
        original_callback = context.approval_callback
        
        async def permission_aware_callback(message: str) -> bool:
            category = tool.category
            
            # Check auto-approve policy
            if category == "read" and self._permissions_config.get("auto_approve_read"):
                return True
            if category == "edit" and self._permissions_config.get("auto_approve_edit"):
                return True
            if category == "command" and self._permissions_config.get("auto_approve_command"):
                return True
                
            # Fallback to original callback if provided
            if original_callback:
                if asyncio.iscoroutinefunction(original_callback):
                    return await original_callback(message)
                return original_callback(message)
            
            # Default Deny if no callback and not auto-approved
            return False

        # Create a new context with the wrapped callback
        # We assume ToolContext is mutable or we create a copy. 
        # Since ToolContext is a simple class, we can modify the instance if we own it,
        # or create a new one. To be safe, let's create a new one if possible, 
        # but ToolContext might have other state.
        # Let's modify the callback on the existing context for this execution.
        
        # But wait, if context is reused, we might stack callbacks.
        # Better to create a proxy context or modify temporarily.
        # Since 'execute' is async and blocking for this tool, we can modify and restore?
        # No, concurrency.
        
        # Let's create a new ToolContext copying fields.
        wrapped_context = ToolContext(
            work_dir=context.work_dir,
            approval_callback=permission_aware_callback,
            state=context.state,
            llm_client=getattr(context, "llm_client", None),
            conversation=getattr(context, "conversation", None),
            provider=getattr(context, "provider", None),
        )
        
        try:
            return await tool.execute(arguments, wrapped_context)
        except Exception as e:
            return ToolResult(f"Tool execution error: {str(e)}", is_error=True)
