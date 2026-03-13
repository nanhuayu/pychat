"""MCP service manager with persistent conversation-scoped sessions."""

import logging
import sys
import os
import asyncio
import json
from dataclasses import dataclass
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
from core.tools.system.shell_exec import (
    ExecuteCommandTool,
    ShellStartTool,
    ShellStatusTool,
    ShellLogsTool,
    ShellWaitTool,
    ShellKillTool,
)
from core.tools.system.patch import PatchTool
from core.tools.system.state_mgr import StateMgrTool
from core.tools.system.multi_agent import NewTaskTool, AttemptCompletionTool, SwitchModeTool
from core.tools.system.document_tools import ManageDocumentTool

logger = logging.getLogger(__name__)


@dataclass
class _PersistentMcpSession:
    signature: str
    stdio_context: Any
    session_context: Any
    session: Any

    async def close(self) -> None:
        session_error: Optional[Exception] = None
        try:
            await self.session_context.__aexit__(None, None, None)
        except Exception as exc:
            session_error = exc
        try:
            await self.stdio_context.__aexit__(None, None, None)
        except Exception as exc:
            if session_error is None:
                session_error = exc
        if session_error is not None:
            raise session_error

class McpManager:
    """MCP service manager.

    Lifecycle is managed by ``AppContainer`` — do not instantiate directly
    outside of the container or ``LLMClient`` fallback path.
    """

    def __init__(self):
        self.storage = StorageService()
        self.servers: List[McpServerConfig] = []
        
        # Initialize Registry
        self.registry = ToolRegistry()
        
        # Register System Tools
        self._register_default_system_tools()
        
        # Search Service
        self.search_service = SearchService(self.storage.load_search_config())
        
        # Helper for legacy
        self._workspace_root = Path(os.getcwd()).resolve()
        self._mcp_schema_cache: Dict[str, Tuple[str, List[Dict[str, Any]]]] = {}
        self._persistent_sessions: Dict[Tuple[str, str], _PersistentMcpSession] = {}

    def _register_default_system_tools(self):
        tools = [
            LsTool(), ReadFileTool(), GrepTool(),
            PythonExecTool(),
            WriteToFileTool(), EditFileTool(), DeleteFileTool(),
            ExecuteCommandTool(),
            ShellStartTool(), ShellStatusTool(), ShellLogsTool(), ShellWaitTool(), ShellKillTool(),
            PatchTool(),
            StateMgrTool(),
            ManageDocumentTool(),
            NewTaskTool(), AttemptCompletionTool(), SwitchModeTool(),
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
        allowed_groups: Optional[set[str]] = None,
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
        
        all_schemas = self.registry.get_all_tool_schemas(allowed_groups=allowed_groups)

        filtered_schemas: List[Dict[str, Any]] = []
        for schema in all_schemas:
            fn = schema.get("function") or {}
            name = fn.get("name")
            if not isinstance(name, str) or not name:
                continue

            is_mcp = name.startswith("mcp__")
            is_search = name == "builtin_web_search"

            if is_search:
                if include_search:
                    filtered_schemas.append(schema)
                continue

            if is_mcp and not include_mcp:
                continue

            filtered_schemas.append(schema)

        return filtered_schemas

    async def _refresh_mcp_tools(self):
        """Register MCP tool proxies using cached schemas where possible."""
        self.servers = self.storage.load_mcp_servers()
        self.registry.unregister_prefix("mcp__")
        active_servers: Dict[str, str] = {}
        
        for config in self.servers:
            if not config.enabled:
                continue
            signature = self._config_signature(config)
            active_servers[config.name] = signature
            
            try:
                cached = self._mcp_schema_cache.get(config.name)
                if cached and cached[0] == signature:
                    schemas = cached[1]
                else:
                    schemas = await self._list_server_tools(config)
                    self._mcp_schema_cache[config.name] = (signature, schemas)

                for schema in schemas:
                    proxy = McpProxyTool(self, config, schema["name"], schema)
                    self.registry.register(proxy)
            except Exception as e:
                logger.warning("Error listing tools from %s: %s", config.name, e)

        stale_cache_keys = [name for name in self._mcp_schema_cache.keys() if name not in active_servers]
        for name in stale_cache_keys:
            self._mcp_schema_cache.pop(name, None)

        stale_session_keys = [
            key for key, handle in self._persistent_sessions.items()
            if key[1] not in active_servers or handle.signature != active_servers.get(key[1])
        ]
        for key in stale_session_keys:
            await self._close_persistent_session(key)

    async def execute_tool_with_context(self, tool_name: str, arguments: dict, context) -> str:
        """
        Delegate execution to Registry.
        Note: Called by the unified runtime (e.g. MessageEngine via UI runtime).
        """
        # `context` is a ToolContext created by the caller.
        result = await self.registry.execute(tool_name, arguments, context)
        return result.to_string()

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        work_dir: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Any:
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

        session_key = self._session_key(conversation_id, server_name)
        for attempt_index in range(2):
            try:
                session = await self._get_or_create_persistent_session(
                    config,
                    conversation_id=conversation_id,
                )
                result = await session.call_tool(real_tool_name, arguments)
                return self._format_tool_result(result)
            except Exception as e:
                logger.warning(
                    "MCP tool call failed (%s -> %s, attempt %s): %s",
                    server_name,
                    real_tool_name,
                    attempt_index + 1,
                    e,
                )
                await self._close_persistent_session(session_key)
                if attempt_index >= 1:
                    return f"MCP Execution Error: {e}"

    async def close_conversation_sessions(self, conversation_id: Optional[str]) -> None:
        conv_key = (conversation_id or "").strip()
        if not conv_key:
            return
        keys = [key for key in self._persistent_sessions.keys() if key[0] == conv_key]
        for key in keys:
            await self._close_persistent_session(key)

    async def shutdown(self) -> None:
        keys = list(self._persistent_sessions.keys())
        for key in keys:
            await self._close_persistent_session(key)

    def _config_signature(self, config: McpServerConfig) -> str:
        payload = {
            "name": config.name,
            "command": config.command,
            "args": list(config.args or []),
            "env": dict(config.env or {}),
            "enabled": bool(config.enabled),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _session_key(self, conversation_id: Optional[str], server_name: str) -> Tuple[str, str]:
        return ((conversation_id or "__global__").strip() or "__global__", server_name)

    def _build_server_params(self, config: McpServerConfig) -> Any:
        env = os.environ.copy()
        env.update(config.env)
        return StdioServerParameters(
            command=config.command,
            args=config.args,
            env=env,
        )

    async def _list_server_tools(self, config: McpServerConfig) -> List[Dict[str, Any]]:
        params = self._build_server_params(config)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()

        schemas: List[Dict[str, Any]] = []
        for tool in result.tools:
            schemas.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                }
            )
        return schemas

    async def _open_persistent_session(self, config: McpServerConfig) -> _PersistentMcpSession:
        params = self._build_server_params(config)
        stdio_context = stdio_client(params)
        read, write = await stdio_context.__aenter__()
        session_context = ClientSession(read, write)
        session = await session_context.__aenter__()
        await session.initialize()
        return _PersistentMcpSession(
            signature=self._config_signature(config),
            stdio_context=stdio_context,
            session_context=session_context,
            session=session,
        )

    async def _get_or_create_persistent_session(
        self,
        config: McpServerConfig,
        *,
        conversation_id: Optional[str],
    ) -> Any:
        key = self._session_key(conversation_id, config.name)
        signature = self._config_signature(config)
        handle = self._persistent_sessions.get(key)
        if handle and handle.signature == signature:
            return handle.session
        if handle:
            await self._close_persistent_session(key)
        handle = await self._open_persistent_session(config)
        self._persistent_sessions[key] = handle
        return handle.session

    async def _close_persistent_session(self, key: Tuple[str, str]) -> None:
        handle = self._persistent_sessions.pop(key, None)
        if not handle:
            return
        try:
            await handle.close()
        except Exception as exc:
            logger.debug("Failed to close MCP session %s: %s", key, exc)

    @staticmethod
    def _format_tool_result(result: Any) -> str:
        text_content: List[str] = []
        for content in getattr(result, "content", []) or []:
            content_type = getattr(content, "type", "")
            if content_type == "text":
                text_content.append(getattr(content, "text", ""))
            elif content_type == "image":
                text_content.append(f"[Image: {getattr(content, 'mimeType', 'unknown')}]")
            elif content_type == "resource":
                text_content.append(f"[Resource: {getattr(content, 'uri', '')}]")
        return "\n".join([item for item in text_content if item])
