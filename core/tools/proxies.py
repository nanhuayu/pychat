from typing import Dict, Any
from core.tools.base import BaseTool, ToolContext, ToolResult

class McpProxyTool(BaseTool):
    """
    A BaseTool wrapper that delegates execution to an external MCP server via McpManager.
    """
    def __init__(self, mcp_manager, config, tool_name: str, schema: Dict[str, Any]):
        self.mcp_manager = mcp_manager
        self.config = config
        self.real_tool_name = tool_name
        self._schema = schema
        # Namespacing: mcp__{server}__{tool}
        self._name = f"mcp__{config.name}__{tool_name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._schema.get("description", "")

    @property
    def category(self) -> str:
        # MCP tools are generally considered "external" or "misc"
        # unless we parse tags. Default to misc (requires approval unless policy says otherwise)
        return "misc"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return self._schema.get("parameters", {})

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        # Delegate to McpManager
        # Note: context.work_dir is passed, but approval is already handled by ToolRegistry wrapper
        try:
            # We call the internal helper of McpManager that handles the raw call
            # But McpManager.call_tool handles connection and execution.
            # We pass the real tool name, not the namespaced one (unless McpManager expects namespaced)
            # McpManager.call_tool expects the full name if it's routing, OR 
            # we can call a lower level method if we know the server.
            
            # Looking at McpManager.call_tool, it seems to expect namespaced name if using _mcp_tool_route.
            # Let's verify McpManager.call_tool implementation.
            
            # If we use McpManager.call_tool(self._name, ...), it should work if McpManager has the route.
            # But here we hold the config directly. We can skip the route lookup.
            
            # Let's add a direct execution method to McpManager or just use call_tool for simplicity.
            # Using call_tool ensures connection management logic in McpManager is used.
            
            result = await self.mcp_manager.call_tool(self._name, arguments, work_dir=context.work_dir)
            return ToolResult(str(result))
        except Exception as e:
            return ToolResult(f"MCP Tool Error: {e}", is_error=True)
