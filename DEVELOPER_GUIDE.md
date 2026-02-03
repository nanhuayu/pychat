# PyChat 开发者指南 (Developer Guide)

本文档旨在为开发者提供 PyChat 项目的深度技术概览，涵盖架构设计、核心模块详解及扩展指南。

## 1. 项目概览 (Project Overview)

PyChat 是一个基于 PyQt6 和 Python 的高级 LLM（大语言模型）客户端，支持多种 LLM 提供商，并集成了强大的 **Agent 模式**。它不仅是一个聊天工具，更是一个具备文件操作、代码执行、上下文管理能力的智能助手。

### 核心特性
*   **双模式引擎**: 支持标准 **Chat 模式** 和自主 **Agent 模式**。
*   **非破坏性上下文压缩**: 采用 "Fresh Start" 策略，通过 `condense_parent` 字段在保留历史记录的同时压缩 Token。
*   **工具生态 (MCP)**: 内置工具注册表，支持 MCP (Model Context Protocol) 协议，易于扩展系统能力。
*   **流式响应架构**: 基于 Qt 信号槽的异步流式处理，保证 UI 响应流畅。

---

## 2. 架构设计 (Architecture)

项目采用分层架构，核心逻辑与 UI 分离，通过 `StreamManager` 进行协调。

```mermaid
graph TD
    UI[UI Layer (PyQt6)] --> Controller[StreamManager]
    Controller --> Core[Core Layer]
    Core --> LLM[LLM Client]
    Core --> Agent[Agent Runner]
    Core --> Tools[Tool Manager]
    Core --> Condense[Context Condenser]
    
    Tools --> SystemTools[System Tools]
    Tools --> MCP[MCP Servers]
    
    LLM --> Provider[Provider Service]
```

### 目录结构
*   `core/`: 核心业务逻辑（Agent, LLM, Tools, Condense）。
*   `controllers/`: 业务控制层（StreamManager）。
*   `models/`: 数据模型（Conversation, Message）。
*   `services/`: 基础设施服务（Storage, Provider）。
*   `ui/`: 界面实现。

---

## 3. 核心模块详解 (Core Modules)

### 3.1 LLM 客户端 (`core/llm`)
负责与 LLM 提供商进行通信的底层模块。

*   **`client.py` (`LLMClient`)**: 统一的入口类。
    *   `send_message(...)`: 处理请求构建、工具上下文注入、流式/非流式请求发送、响应解析。
*   **`request_builder.py`**: 构建 API 请求体。
    *   `select_base_messages(...)`: 根据 `max_context_messages` 和 `condense_parent` 筛选有效历史记录。
    *   **关键逻辑**: 防止截断 Assistant-Tool 对，避免 API 400 错误。
*   **`thinking_parser.py`**: 解析带有思维链（Thinking/Reasoning）的模型响应。

### 3.2 Agent 系统 (`core/agent`)
实现自主智能体的 "Think-Act" 循环。

*   **`runner.py` (`AgentRunner`)**: Agent 的心脏。
    *   `run_task(...)`: 执行主循环。
        1.  **Context Management**: 检查 Token 和消息数，触发压缩。
        2.  **LLM Call**: 获取模型响应。
        3.  **Tool Execution**: 解析并执行工具调用。
        4.  **Loop**: 重复直到任务完成或达到最大轮数。
    *   `_manage_context(...)`: 监控活跃消息数（默认阈值 15）和 Token 使用量，调用 `Condenser`。
*   **`task.py` (`AgentTask`)**: 记录任务状态、历史和成本。

### 3.3 上下文压缩 (`core/condense`)
解决长对话 Token 爆炸问题的核心机制。

*   **`condenser.py` (`ContextCondenser`)**:
    *   **Message Condensation**: 对单条过长消息（如大文件读取结果）生成摘要 (`message.summary`)。
    *   **Global Condensation ("Fresh Start")**:
        1.  生成历史摘要。
        2.  插入 Summary 消息。
        3.  标记旧消息的 `condense_parent`，使其在后续请求中被过滤，但在 UI 中保留。
    *   **Self-Healing**: 自动清洗“孤儿” Tool 消息（丢失父 Assistant 的工具结果），防止 API 报错。

### 3.4 工具系统 (`core/tools`)
*   **`manager.py` (`McpManager`)**: 管理工具注册和发现。
    *   `get_all_tools(...)`: 获取工具 Schema（按 `include_mcp/include_search` 过滤）。
    *   `execute_tool_with_context(...)`: 执行工具。
*   **`registry.py` (`ToolRegistry`)**: 内存中的工具注册表。
*   **`system/`**: 内置系统工具。
    *   `filesystem.py`: `ls`, `read_file`, `grep`.
    *   `file_ops.py`: `write_file`, `edit_file` (Search/Replace), `delete_file`.
    *   `shell_exec.py`: `execute_command` (支持交互式命令模拟).
    *   `patch.py`: `apply_patch` (支持模糊匹配的 Diff 应用).

---

## 4. 数据模型 (Data Models)

### 4.1 Conversation (`models/conversation.py`)
*   `messages`: 消息列表。
*   `mode`: 会话模式 (`"chat"` 或 `"agent"`)。
*   `work_dir`: 会话关联的工作目录。

### 4.2 Message (`models/conversation.py`)
*   `role`: `user`, `assistant`, `system`, `tool`.
*   `content`: 消息内容。
*   `tool_calls`: 工具调用请求（Assistant）。
*   `tool_call_id`: 工具调用 ID（Tool）。
*   `summary`: **[关键]** 该消息的压缩摘要（用于 API 请求）。
*   `condense_parent`: **[关键]** 指向“吞噬”了该消息的 Summary 消息 ID。

---

## 5. UI 架构 (UI Architecture)

### 5.1 Main Window (`ui/main_window.py`)
主窗口，负责组装各个组件。
*   初始化 `LLMClient`, `McpManager`, `StreamManager`.
*   连接信号槽。

### 5.2 Stream Manager (`controllers/stream_manager.py`)
负责将异步的 LLM 请求桥接到 PyQt 的 UI 线程。
*   **线程模型**: 在后台线程运行 `asyncio` 事件循环，执行 `LLMClient` 或 `AgentRunner`。
*   **模式策略**: `chat` 模式强制关闭 MCP 工具；`agent` 模式可启用 MCP 工具。
*   **信号 (`pyqtSignal`)**:
    *   `token_received`: 实时文本 Token。
    *   `thinking_received`: 实时思维链内容。
    *   `response_step`: 中间步骤（如工具执行结果）。
    *   `response_complete`: 完成信号。

---

## 6. 开发指南 (Development Guide)

### 6.1 添加新工具
1.  在 `core/tools/system/` 下创建新文件（例如 `my_tool.py`）。
2.  继承 `BaseTool` 并实现 `execute` 方法。
3.  在 `core/tools/manager.py` 的 `_register_default_system_tools` 中注册。

```python
# 示例
class MyTool(BaseTool):
    @property
    def name(self) -> str: return "my_tool"
    
    async def execute(self, args, context):
        return ToolResult("Hello from MyTool")
```

### 6.2 修改 Agent 行为
*   **调整 Prompt**: 修改 `core/prompts/system.py`。
*   **调整压缩策略**: 修改 `core/agent/runner.py` 中的 `_manage_context` 阈值。

### 6.3 调试技巧
*   **日志**: 检查工作目录下的 `debug_request_*.json` 文件查看实际发送给 API 的 Payload。
*   **Agent 状态**: 查看 `tasks/task_*.json` 获取 Agent 内部状态和历史。

---

## 7. 常见问题 (Troubleshooting)

*   **HTTP 400 (Invalid parameter: messages with role 'tool'...)**:
    *   原因：历史记录被截断，导致 `tool` 消息失去了对应的 `assistant` 父消息。
    *   解决：`core/prompts/system.py` 会自动将孤儿 `tool` 消息转换为 `user` 消息。

*   **Payload 过大**:
    *   原因：压缩未触发或 `summary` 字段未被正确使用。
    *   解决：检查 `AgentRunner` 的 `message_count_threshold` 配置。
