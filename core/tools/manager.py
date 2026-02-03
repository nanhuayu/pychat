"""
MCP Service Manager (Refactored)
Manages connections to MCP servers and acts as a provider for the ToolRegistry.
"""

import sys
import os
import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    ClientSession = object
    StdioServerParameters = object

from models.mcp_server import McpServerConfig
from services.storage_service import StorageService
from services.search_service import SearchService

from core.tools.registry import ToolRegistry
from core.tools.proxies import McpProxyTool
from core.tools.system.search import WebSearchTool

# System Tools
from core.tools.system.filesystem import LsTool, ReadFileTool, GrepTool
from core.tools.system.python_exec import PythonExecTool
from core.tools.system.file_ops import WriteToFileTool, EditFileTool, DeleteFileTool
from core.tools.system.shell_exec import ExecuteCommandTool
from core.tools.system.memory import MemoryTool
from core.tools.system.skills import SkillTool
from core.tools.system.patch import PatchTool
from core.tools.system.todo import TodoListTool

class McpManager:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(McpManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
            
        self.storage = StorageService()
        self.servers: List[McpServerConfig] = []
        # We don't maintain persistent sessions for stateless tool listing in this design,
        # but for execution we might need to if we want state.
        # For now, we follow the previous pattern of connect-on-demand for listing.
        
        self.initialized = True
        
        # Initialize Registry
        self.registry = ToolRegistry()
        
        # Register System Tools
        self._register_default_system_tools()
        
        # Search Service
        self.search_service = SearchService(self.storage.load_search_config())
        
        # Helper for legacy
        self._workspace_root = Path(os.getcwd()).resolve()

    def _register_default_system_tools(self):
        tools = [
            LsTool(), ReadFileTool(), GrepTool(),
            PythonExecTool(),
            WriteToFileTool(), EditFileTool(), DeleteFileTool(),
            ExecuteCommandTool(),
            MemoryTool(), SkillTool(),
            PatchTool(), TodoListTool()
        ]
        for tool in tools:
            self.registry.register(tool)

    def update_permissions(self, config: Dict[str, Any]):
        """Update permission settings in Registry."""
        self.registry.update_permissions(config)

    async def get_all_tools(
        self,
        include_search: bool = False,
        include_mcp: bool = False,
        prepared_queries: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Refreshes tools in the registry (if needed) and returns schemas.
        """
        # 1. Search Tool
        # Search tool logic is a bit dynamic (prepared_queries).
        # We might need to re-register it if queries change?
        # Or just register a generic one and let args handle it.
        # For compatibility with existing SearchService logic, let's just wrap it.
        if include_search and self.search_service.is_available():
            # Create a dynamic instance or update existing
            # For simplicity, we register a new instance
            search_tool = WebSearchTool(self.search_service, prepared_queries)
            self.registry.register(search_tool)

        # 2. MCP Tools
        if include_mcp and MCP_AVAILABLE:
            await self._refresh_mcp_tools()

        # 3. Return schemas from Registry
        # Filter based on what was requested?
        # The Registry holds ALL tools.
        # If the caller only wanted some, we might need filtering.
        # But usually we want all available tools.
        # If 'include_mcp' is False, we should filter out MCP tools?
        # Yes, for performance/context size.
        
        all_schemas = self.registry.get_all_tool_schemas()
        
        filtered_schemas = []
        for schema in all_schemas:
            name = schema["function"]["name"]
            
            # Identify tool type by name prefix or registry metadata
            is_mcp = name.startswith("mcp__")
            is_search = name == "builtin_web_search"
            
            if is_mcp and not include_mcp:
                continue
            if is_search and not include_search:
                continue
                
            filtered_schemas.append(schema)
            
        return filtered_schemas

    async def _refresh_mcp_tools(self):
        """Connects to enabled servers and registers their tools."""
        self.servers = self.storage.load_mcp_servers()
        
        for config in self.servers:
            if not config.enabled:
                continue
            
            try:
                # We need to list tools.
                # This logic is similar to previous get_all_tools.
                env = os.environ.copy()
                env.update(config.env)
                
                params = StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    env=env
                )
                
                # Connect and list
                # Note: This is slow if we do it every time.
                # We should cache or only do it if not done recently.
                # For now, keeping it simple as per previous implementation.
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
                        
                        for tool in result.tools:
                            # Create Proxy
                            schema = {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters": tool.inputSchema
                            }
                            proxy = McpProxyTool(self, config, tool.name, schema)
                            self.registry.register(proxy)
                            
            except Exception as e:
                print(f"Error listing tools from {config.name}: {e}")

    async def execute_tool_with_context(self, tool_name: str, arguments: dict, context) -> str:
        """
        Delegate execution to Registry.
        Note: StreamManager calls this.
        """
        # We need to import ToolContext if 'context' is not typed, but it is passed from StreamManager.
        result = await self.registry.execute(tool_name, arguments, context)
        return result.to_string()

    async def call_tool(self, tool_name: str, arguments: dict, work_dir: Optional[str] = None) -> Any:
        """
        Execute an MCP tool (called by McpProxyTool).
        Handles the connection management.
        """
        # Parse tool name to find config
        # tool_name is "mcp__{server}__{tool}"
        # We need to reverse map or iterate configs.
        # But McpProxyTool knows the config! 
        # Wait, McpProxyTool called self.call_tool(self._name, ...)
        # If we pass the Config object to call_tool, it's easier.
        # But McpManager.call_tool signature is (tool_name, args, work_dir).
        
        # Let's find the config from the name.
        parts = tool_name.split("__")
        if len(parts) < 3:
             return f"Invalid MCP tool name: {tool_name}"
        
        server_name = parts[1]
        real_tool_name = "__".join(parts[2:])
        
        # Find config
        config = next((c for c in self.servers if c.name == server_name), None)
        if not config:
            # Try reloading
            self.servers = self.storage.load_mcp_servers()
            config = next((c for c in self.servers if c.name == server_name), None)
            
        if not config:
            return f"Server {server_name} not found or disabled"

        # Execute
        try:
            env = os.environ.copy()
            env.update(config.env)
            
            params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=env
            )
            
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(real_tool_name, arguments)
                    
                    # Result is CallToolResult
                    # We need to format it to string
                    text_content = []
                    for content in result.content:
                        if content.type == "text":
                            text_content.append(content.text)
                        elif content.type == "image":
                            text_content.append(f"[Image: {content.mimeType}]")
                        elif content.type == "resource":
                             text_content.append(f"[Resource: {content.uri}]")
                             
                    return "\n".join(text_content)
                    
        except Exception as e:
            return f"MCP Execution Error: {e}"
