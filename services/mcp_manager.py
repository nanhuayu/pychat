"""
MCP Service Manager
Manages connections to MCP servers, tool aggregation, and execution.
Requires 'mcp' package (pip install mcp).
"""

import sys
import os
import asyncio
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    # Mock classes to prevent crash if not installed
    ClientSession = object
    StdioServerParameters = object

from models.mcp_server import McpServerConfig
from services.storage_service import StorageService
from services.search_service import SearchService

from core.tools.base import BaseTool, ToolContext
from core.tools.system.filesystem import LsTool, ReadFileTool, GrepTool
from core.tools.system.python_exec import PythonExecTool
from core.tools.system.file_ops import WriteToFileTool, EditFileTool, DeleteFileTool
from core.tools.system.shell_exec import ExecuteCommandTool
from core.tools.system.memory import MemoryTool
from core.tools.system.planning import PlanTool
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
        self.active_sessions: Dict[str, ClientSession] = {}
        self.exit_stack = None
        self.initialized = True
        self._tools_cache: List[Dict[str, Any]] = []
        self._mcp_tool_route: Dict[str, Tuple[McpServerConfig, str]] = {}
        
        # Search service integration
        self.search_service = SearchService(self.storage.load_search_config())
        self._search_enabled = False  # Runtime toggle from UI
        self._prepared_search_queries: List[str] = []

        # Built-in "default MCP" tools (no external server required)
        self._workspace_root = Path(os.getcwd()).resolve()
        
        # Initialize System Tools
        self._system_tools: Dict[str, BaseTool] = {}
        self._register_system_tool(LsTool())
        self._register_system_tool(ReadFileTool())
        self._register_system_tool(GrepTool())
        self._register_system_tool(PythonExecTool())
        self._register_system_tool(WriteToFileTool())
        self._register_system_tool(EditFileTool())
        self._register_system_tool(DeleteFileTool())
        self._register_system_tool(ExecuteCommandTool())
        self._register_system_tool(MemoryTool())
        self._register_system_tool(PlanTool())
        self._register_system_tool(SkillTool())
        self._register_system_tool(PatchTool())
        self._register_system_tool(TodoListTool())
        
        # Permissions Configuration
        self._permissions_config: Dict[str, Any] = {
            "auto_approve_read": True,
            "auto_approve_edit": False,
            "auto_approve_command": False
        }

    def update_permissions(self, config: Dict[str, Any]):
        """Update permission settings from app settings."""
        self._permissions_config.update({
            k: v for k, v in config.items() 
            if k in self._permissions_config
        })

    def _register_system_tool(self, tool: BaseTool):
        self._system_tools[tool.name] = tool

    def _resolve_path_in_workspace(self, p: str, work_dir: Optional[Path] = None) -> Path:
        # Legacy helper, kept for backward compatibility if needed, 
        # but tools now handle this via ToolContext.
        p = (p or ".").strip() or "."
        root = work_dir if work_dir else self._workspace_root
        candidate = (root / p).resolve() if not os.path.isabs(p) else Path(p).resolve()
        try:
            candidate.relative_to(root)
        except Exception:
            raise ValueError(f"Path is outside workspace: {root}")
        return candidate


    def _builtin_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._system_tools.values()]

    def load_servers(self):
        """Load servers from storage"""
        self.servers = self.storage.load_mcp_servers()
        # Reload search config
        self.search_service.update_config(self.storage.load_search_config())

    async def initialize_server(self, config: McpServerConfig) -> Optional[ClientSession]:
        """Initialize a connection to a single MCP server"""
        if not MCP_AVAILABLE:
            print("MCP package not installed")
            return None
            
        try:
            # We can't use 'async with' freely here because we want to keep sessions alive.
            # However, mcp's stdio_client is a context manager.
            # We need to maintain the context stack.
            # Simplified approach: We will use a custom context manager helper or just re-connect on demand/maintain long-running task.
            # For simplicity in this architecture, we will use a global ExitStack in the future, 
            # or just launch per-request for now (safe but slow) OR use a background task loop.
            
            # Since MCP sessions are stateful, we really want them persistent.
            # But implementing persistent async context managers inside a simple manager class is complex.
            # Let's try to wrap them.
            
            # NOTE: For MVP, we might just instantiate StdioServerParameters and let the client handle it.
            # But standard usage is `async with stdio_client(...)`.
            
            # Alternative: Just return the params and let the caller context-manage (but caller is ChatService).
            # ChatService is transient.
            
            # Better: Connect to all enabled servers at application startup (or first use)
            # and keep them running.
            pass
        except Exception as e:
            print(f"Failed to init MCP server {config.name}: {e}")
            return None

    # For this refactoring, managing long-lived asyncio context managers across PyQt event loop is HARD.
    # Strategy: Connect on demand for "list tools" (caching) and "call tool" (short-lived).
    # This acts like a "stateless" HTTP router, but for Stdio. 
    # Pros: Robust, no zombie processes. Cons: Higher latency per turn.
    # Given requirements "Clean and Concise", stateless is best.
    
    async def get_all_tools(
        self,
        include_search: bool = False,
        include_mcp: bool = False,
        prepared_queries: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Connect to all enabled servers, list tools, and cache them."""
        tools_list: List[Dict[str, Any]] = []
        self._mcp_tool_route = {}
        
        # Add search tool if enabled
        if include_search and self.search_service.is_available():
            self._prepared_search_queries = [q.strip() for q in (prepared_queries or []) if isinstance(q, str) and q.strip()]
            search_tool = self.search_service.get_tool_schema(prepared_queries=self._prepared_search_queries)
            if search_tool:
                tools_list.append(search_tool)

        # Add built-in default tools if MCP is enabled (no external servers required)
        if include_mcp:
            tools_list.extend(self._builtin_tools())
        
        # Skip external MCP server tools if not requested or not available
        if not include_mcp or not MCP_AVAILABLE:
            self._tools_cache = tools_list
            return tools_list
            
        self.load_servers()
        
        for config in self.servers:
            if not config.enabled:
                continue
                
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
                        # List tools
                        result = await session.list_tools()
                        # Convert to OpenAI format
                        for tool in result.tools:
                            # OpenAI format: { "type": "function", "function": { "name": "...", "description": "...", "parameters": ... } }
                            # Need to prefix name to avoid collisions? e.g. "server__tool"
                            openai_tool = {
                                "type": "function",
                                "function": {
                                    "name": "",
                                    "description": tool.description,
                                    "parameters": tool.inputSchema
                                }
                            }

                            # Namespace to avoid collision with built-ins.
                            # Use a stable prefix and keep the original config.name for readability.
                            namespaced = f"mcp__{config.name}__{tool.name}"
                            openai_tool["function"]["name"] = namespaced
                            self._mcp_tool_route[namespaced] = (config, tool.name)
                            tools_list.append(openai_tool)
                            
            except Exception as e:
                print(f"Error listing tools from {config.name}: {e}")
                
        self._tools_cache = tools_list
        return tools_list

    async def execute_tool_with_context(self, tool_name: str, arguments: dict, context: ToolContext) -> str:
        """Execute a tool using a provided context (preserves state)."""
        
        # Wrap approval callback with permission check
        original_callback = context.approval_callback
        
        # Identify category
        category = "misc"
        if tool_name in self._system_tools:
            category = self._system_tools[tool_name].category
        
        async def permission_aware_callback(message: str) -> bool:
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
            
            # Default: If no callback and not auto-approved, DENY for safety (except 'misc' or 'read'?)
            # BaseTool defaults to True if no callback.
            # But if we are here, we are enforcing policy.
            # If the user explicitly disabled auto-approve, and there is no UI callback, we MUST deny.
            return False

        # Inject wrapped callback
        # We need to monkey-patch the context instance or create a proxy?
        # ToolContext has approval_callback attribute.
        context.approval_callback = permission_aware_callback

        # 1. System Tools
        if tool_name in self._system_tools:
            tool = self._system_tools[tool_name]
            try:
                result = await tool.execute(arguments, context)
                return result.to_string()
            except Exception as e:
                return f"Tool execution error: {e}"

        # 2. External MCP Tools (Stateless for now regarding 'context.state', but use context.work_dir)
        # We delegate to the existing logic but we need to adapt.
        # The existing logic is inside call_tool.
        # Let's reuse call_tool logic but we can't easily inject state into stdio_client yet.
        # So we just call call_tool. External tools don't share our memory dict anyway.
        return await self.call_tool(tool_name, arguments, work_dir=context.work_dir)

    async def call_tool(self, tool_name: str, arguments: dict, work_dir: Optional[str] = None) -> Any:
        """Execute a tool. Handles both search and MCP tools."""
        
        # Determine effective workspace root
        effective_root = self._workspace_root
        if work_dir and os.path.isdir(work_dir):
            try:
                effective_root = Path(work_dir).resolve()
            except Exception:
                pass

        # Ensure configs are loaded
        if not self.servers:
            try:
                self.load_servers()
            except Exception:
                pass
        
        # Handle built-in web search (Cherry: builtin_web_search)
        if tool_name in {"builtin_web_search", "web_search"}:
            if not isinstance(arguments, dict):
                arguments = {}

            base_query = ""
            if self._prepared_search_queries:
                base_query = self._prepared_search_queries[0]

            query = (arguments.get("query") or "").strip() if isinstance(arguments.get("query"), str) else ""
            additional = (arguments.get("additionalContext") or "").strip() if isinstance(arguments.get("additionalContext"), str) else ""

            if query:
                final_query = query
            elif additional:
                final_query = f"{base_query} {additional}".strip() if base_query else additional
            elif base_query:
                final_query = base_query
            else:
                return "Search query missing"

            return await self.search_service.search(final_query)

        # Built-in system tools (Modularized)
        if tool_name in self._system_tools:
            tool = self._system_tools[tool_name]
            if not isinstance(arguments, dict):
                arguments = {}
            
            # Create context with approval callback placeholder
            # TODO: Hook up UI callback for approval
            context = ToolContext(
                work_dir=str(effective_root),
                approval_callback=None 
            )
            
            try:
                result = await tool.execute(arguments, context)
                return result.to_string()
            except Exception as e:
                return f"Tool execution error: {e}"

        
        # Handle external MCP tools
        if not MCP_AVAILABLE:
            return "MCP subsystem unavailable"

        config: Optional[McpServerConfig] = None
        real_tool_name: str = ""

        routed = self._mcp_tool_route.get(tool_name)
        if routed:
            config, real_tool_name = routed
        else:
            # Backward-compatible fallback: 'Server__Tool'
            if "__" not in tool_name:
                return f"Invalid tool name format: {tool_name}"
            server_name, real_tool_name = tool_name.split("__", 1)
            config = next((s for s in self.servers if s.name == server_name and s.enabled), None)
            if not config:
                return f"Server {server_name} not found or disabled"
            
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
                    
                    # Result is a ToolResult object (content list)
                    # We need to flatten it to string for LLM
                    output_text = []
                    if hasattr(result, 'content'):
                        for item in result.content:
                            if getattr(item, 'type', '') == 'text':
                                output_text.append(item.text)
                            elif getattr(item, 'type', '') == 'image':
                                output_text.append(f"[Image: {item.mimeType}]")
                                
                    return "\n".join(output_text)
                    
        except Exception as e:
            return f"Error executing tool {real_tool_name} on {server_name}: {e}"

