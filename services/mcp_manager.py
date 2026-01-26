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

    def _resolve_path_in_workspace(self, p: str) -> Path:
        p = (p or ".").strip() or "."
        candidate = (self._workspace_root / p).resolve() if not os.path.isabs(p) else Path(p).resolve()
        try:
            candidate.relative_to(self._workspace_root)
        except Exception:
            raise ValueError("Path is outside workspace")
        return candidate

    def _builtin_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "builtin_filesystem_ls",
                    "description": "List files and directories under a workspace path.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Workspace-relative path. Default: '.'"},
                            "recursive": {"type": "boolean", "description": "List recursively. Default: false"},
                            "maxEntries": {"type": "number", "description": "Limit returned entries to avoid huge output. Default: 200"},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "builtin_filesystem_read",
                    "description": "Read a text file under the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Workspace-relative file path"},
                            "maxBytes": {"type": "number", "description": "Max bytes to read (default: 20000)"},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "builtin_filesystem_grep",
                    "description": "Search for a regex in text files under a workspace directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Workspace-relative directory. Default: '.'"},
                            "pattern": {"type": "string", "description": "Regex pattern"},
                            "include": {"type": "string", "description": "Optional glob include pattern, e.g. '**/*.py'"},
                            "maxMatches": {"type": "number", "description": "Max matches (default: 50)"},
                        },
                        "required": ["pattern"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "builtin_python_exec",
                    "description": "Execute Python code locally (no sandbox). Returns stdout/stderr. Use for quick calculations or small scripts.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Python code to execute"},
                            "timeoutSec": {"type": "number", "description": "Timeout seconds (default: 10)"},
                            "cwd": {"type": "string", "description": "Workspace-relative working directory (default: '.')"},
                        },
                        "required": ["code"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

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

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Execute a tool. Handles both search and MCP tools."""

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

        # Built-in default MCP tools
        if tool_name == "builtin_filesystem_ls":
            if not isinstance(arguments, dict):
                arguments = {}
            path = arguments.get("path", ".")
            recursive = bool(arguments.get("recursive", False))
            max_entries = int(arguments.get("maxEntries", 200) or 200)
            max_entries = max(1, min(max_entries, 2000))
            try:
                base = self._resolve_path_in_workspace(str(path))
            except Exception as e:
                return f"Invalid path: {e}"

            if not base.exists():
                return f"Not found: {base}"

            entries: List[Dict[str, Any]] = []

            def add_entry(p: Path):
                try:
                    rel = str(p.relative_to(self._workspace_root)).replace("\\", "/")
                except Exception:
                    rel = str(p)
                try:
                    stat = p.stat()
                    size = int(stat.st_size)
                except Exception:
                    size = None
                entries.append({
                    "path": rel,
                    "name": p.name,
                    "type": "dir" if p.is_dir() else "file",
                    "size": size,
                })

            try:
                if base.is_dir():
                    if recursive:
                        for p in base.rglob("*"):
                            add_entry(p)
                            if len(entries) >= max_entries:
                                break
                    else:
                        for p in base.iterdir():
                            add_entry(p)
                            if len(entries) >= max_entries:
                                break
                else:
                    add_entry(base)
            except Exception as e:
                return f"List error: {e}"

            return json.dumps({"root": str(self._workspace_root).replace("\\", "/"), "entries": entries}, ensure_ascii=False, indent=2)

        if tool_name == "builtin_filesystem_read":
            if not isinstance(arguments, dict):
                arguments = {}
            path = str(arguments.get("path", "") or "").strip()
            max_bytes = int(arguments.get("maxBytes", 20000) or 20000)
            max_bytes = max(100, min(max_bytes, 200000))
            if not path:
                return "Missing 'path'"
            try:
                file_path = self._resolve_path_in_workspace(path)
            except Exception as e:
                return f"Invalid path: {e}"
            if not file_path.exists() or not file_path.is_file():
                return f"Not a file: {file_path}"
            try:
                data = file_path.read_bytes()[:max_bytes]
                try:
                    text = data.decode("utf-8")
                except Exception:
                    text = data.decode("utf-8", errors="replace")
                return text
            except Exception as e:
                return f"Read error: {e}"

        if tool_name == "builtin_filesystem_grep":
            import re
            if not isinstance(arguments, dict):
                arguments = {}
            root = arguments.get("path", ".")
            pattern = arguments.get("pattern", "")
            include = arguments.get("include")
            max_matches = int(arguments.get("maxMatches", 50) or 50)
            max_matches = max(1, min(max_matches, 500))
            if not isinstance(pattern, str) or not pattern:
                return "Missing 'pattern'"
            try:
                root_path = self._resolve_path_in_workspace(str(root))
            except Exception as e:
                return f"Invalid path: {e}"
            if not root_path.exists() or not root_path.is_dir():
                return f"Not a directory: {root_path}"

            try:
                rx = re.compile(pattern)
            except Exception as e:
                return f"Invalid regex: {e}"

            glob_pattern = include if isinstance(include, str) and include.strip() else "**/*"
            matches: List[Dict[str, Any]] = []
            for p in root_path.glob(glob_pattern):
                if len(matches) >= max_matches:
                    break
                if not p.is_file():
                    continue
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for i, line in enumerate(content.splitlines(), 1):
                    if rx.search(line):
                        try:
                            rel = str(p.relative_to(self._workspace_root)).replace("\\", "/")
                        except Exception:
                            rel = str(p)
                        matches.append({"path": rel, "line": i, "text": line[:300]})
                        if len(matches) >= max_matches:
                            break
            return json.dumps({"matches": matches, "count": len(matches)}, ensure_ascii=False, indent=2)

        if tool_name == "builtin_python_exec":
            if not isinstance(arguments, dict):
                arguments = {}
            code = arguments.get("code", "")
            timeout_sec = float(arguments.get("timeoutSec", 30) or 30)
            cwd = arguments.get("cwd", ".")
            if not isinstance(code, str) or not code.strip():
                return "Missing 'code'"
            timeout_sec = max(1.0, min(timeout_sec, 60.0))
            try:
                cwd_path = self._resolve_path_in_workspace(str(cwd))
            except Exception as e:
                return f"Invalid cwd: {e}"

            try:
                proc = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=str(cwd_path),
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                return json.dumps(
                    {
                        "exitCode": proc.returncode,
                        "stdout": (proc.stdout or "").strip(),
                        "stderr": (proc.stderr or "").strip(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            except subprocess.TimeoutExpired:
                return f"Python execution timed out after {timeout_sec:.0f}s"
            except Exception as e:
                return f"Python execution error: {e}"
        
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

