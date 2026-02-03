# PyChat 架构与代码组织

## 当前分层

```
pychat/
├── main.py             # 应用入口
├── models/              # 纯数据模型（无外部依赖）
│   ├── conversation.py  # Conversation, Message (含 seq_id, state_snapshot)
│   ├── state.py         # SessionState, Task, TaskStatus (状态管理核心)
│   ├── provider.py      # Provider 模型
│   ├── mcp_server.py    # MCP 服务器配置
│   └── search_config.py # 搜索配置
│
├── utils/               # 纯工具函数（无 UI/services 依赖）
│   └── image_encoding.py # encode_image_file_to_data_url
│
├── services/            # 本地持久化 + 外部能力（Provider/Search）
│   ├── storage_service.py   # 本地 JSON 持久化
│   ├── provider_service.py  # Provider 管理
│   ├── search_service.py    # 网络搜索服务 (Tavily/Google/SearXNG)
│   └── importers/           # 导入格式解析
│       ├── parse.py         # 统一入口
│       └── *.py             # 各格式解析器
│
├── core/               # 可复用业务能力（LLM/Prompt/Modes/Tools/State）
│   ├── llm/            # LLM 请求构建 + HTTP/流式解析
│   │   ├── client.py   # LLMClient（原 ChatService 的定位）
│   │   └── request_builder.py
│   ├── prompts/        # system prompt 生成（Mode 驱动）
│   ├── modes/          # 多模式系统（defaults + work_dir/modes.json）
│   ├── tools/          # MCP/系统工具注册与执行（ToolRegistry/McpManager）
│   ├── condense/       # 会话压缩/总结
│   ├── prompt_optimize/ # 提示词优化 prompts
│   ├── agent/          # AgentRunner（多步工具/规划）
│   └── state/          # 会话 state 相关服务
│
├── controllers/         # 业务编排层
│   ├── stream_manager.py   # 并发流式管理 + tool-calls 回路
│   └── prompt_optimizer.py # 提示词优化后台任务
│
└── ui/                  # PyQt6 UI 层
    ├── main_window.py   # 主窗口
    ├── widgets/         # 可复用组件
    ├── dialogs/         # 对话框
    ├── settings/        # 设置模块 (单文件)
    │   └── settings_dialog.py  # 统一设置对话框
    └── utils/           # Qt 相关工具
        ├── image_loader.py  # QPixmap 加载
        └── image_utils.py   # 剪贴板/拖放图片处理
```

## 依赖关系（重要）

```
models  ←─ utils ←─ services
  ▲                ▲
  │                │
  └──── core ──────┘
           ▲
           │
     controllers ←─ ui
```

说明：这是“当前实际依赖”的近似图。`core/tools/manager.py` 会引用 `services/storage_service.py` 与 `services/search_service.py`（用于加载 MCP/Search 配置与执行搜索），因此 `core` 与 `services` 目前是互相协作关系，而非严格单向分层。

## 建议的简化架构（路线图）

目标：把“UI 事件 / 会话状态 / LLM 请求 / 模式&提示词 / 工具能力”分离成清晰的 4 层，减少 `ui/main_window.py` 里夹杂的业务逻辑。

### 1) Domain（纯数据）
- `models/conversation.py`
  - `Conversation`/`Message` 只管数据结构与序列化
  - `Conversation.mode` 作为“模式 slug”（例如 `chat`/`agent`/`debug`）

### 2) Core（可复用业务能力）
- `core/modes/`
  - `types.py`：`ModeConfig`/groups 等
  - `defaults.py`：内置默认模式
  - `manager.py`：加载内置 + 可选 `work_dir/modes.json`
- `core/prompts/system.py`
  - system prompt 的“主体”由 mode 决定
  - tool/workspace framing 由策略决定（避免 Chat/Agent 混用规则）
- `core/llm/request_builder.py`
  - 只做“结构化 payload 构建”，不关心 UI

### 3) Application（用例编排，建议新增）
建议新增一层把“发送/流式/总结/优化/能力开关”等用例从 UI 移走：
- `core/app/chat_app.py`
  - 用例：`send_message` / `start_stream` / `optimize_prompt` / `condense`
  - 输入：`Conversation` + `Provider` + `RunConfig`（mode、mcp/search/thinking 等）
  - 输出：`Message` / stream events

### 4) UI（展示 + 事件转发）
- `ui/main_window.py`
  - 只负责 wiring：把 UI 信号转给 Application 层
  - 不直接拼装 prompt，不直接决定模式能力
- `ui/widgets/input_area.py`
  - 只负责采集输入、展示按钮、发信号

### 为什么要这样
- `MainWindow` 复杂度下降：不再同时承担“状态机 + 业务规则 + UI”
- 模式系统可扩展：新增/调整模式只改 `modes.json` 或 defaults
- Prompt 更可控：mode 驱动 prompt，避免把工具规则泄漏到纯聊天模式

## 项目模式配置（可选）
在工作区根目录放 `modes.json`：
- 结构参考仓库中的 `modes.example.json`
- 应用会在切换 work_dir 时自动刷新模式列表

## 数据流

### 1) 启动

`main.py` → `MainWindow()` →
- `StorageService.load_settings/load_providers/list_conversations`
- `InputArea.set_providers()`
- `Sidebar.update_conversations()`

### 2) 发送消息

`InputArea.message_sent` → `MainWindow._send_message()`：
- 校验 provider/model
- 追加 user `Message` 到 `Conversation`
- `StorageService.save_conversation()`
- `ChatView.add_message()`
- 然后启动流式：`StreamManager.start(...)`

### 3) 并发流式

**核心设计**：每个会话一个 in-flight state，互不影响。

- `StreamManager` 维护 `conversation_id -> ConversationStreamState`：
  - `request_id`：用于丢弃旧请求事件（防串线）
  - `cancel_event`：每请求独立取消
  - `visible_text/thinking_text`：切换会话后恢复 UI

- 线程/异步：
  - 后台线程创建 event loop 调用 `LLMClient.send_message()`
  - 通过 Qt signal 把 token/thinking/complete/error 安全地回传主线程

### 4) 切换会话时的恢复

`Sidebar.conversation_selected` → `MainWindow._on_conversation_selected()`：
- `StorageService.load_conversation()`
- `ChatView.load_conversation()`
- 如果该会话仍在生成：从 `StreamManager.get_state()` 取缓存文本，调用 `ChatView.restore_streaming_state()`

### 5) system prompt / mode / 能力开关

- Mode：`Conversation.mode` 为模式 slug，由 `core/modes/ModeManager` 提供内置默认模式，并可从 `work_dir/modes.json` 覆盖。
- system prompt：`core/prompts/system.py` 的 `PromptManager` 负责生成系统提示词，主体由 mode 驱动；`core/llm/request_builder.py` 会把 system message 注入到 payload。
- 能力开关：UI 的 MCP/Search/Thinking 开关会影响 `LLMClient.send_message(... enable_mcp/enable_search/enable_thinking ...)`，并进一步影响工具 schema 注入与 tool-call 执行。

## 模块职责

| 模块 | 职责 | 行数约 |
|-----|-----|-------|
| `LLMClient` | LLM 请求编排（构建 payload、注入工具、HTTP/流式收发） | ~300 |
| `request_builder` | 构建 API messages/body（system message 注入、消息结构化） | ~200 |
| `PromptManager` | system prompt 生成（Mode 驱动，含可选 workspace/tool framing） | ~200 |
| `ModeManager` | 模式加载（defaults + `work_dir/modes.json`） | ~120 |
| `McpManager` | 工具 schema 汇总（系统工具/搜索/外部 MCP）+ 工具执行入口 | ~250 |
| `ToolRegistry` | 工具注册与权限封装执行（read/edit/command） | ~120 |
| `http_utils` | HTTP 错误格式化、SSE 解析 | ~100 |
| `thinking_parser` | `<think>`/`<analysis>` 标签提取 | ~80 |
| `StreamManager` | 并发流式状态管理 | ~200 |
| `PromptOptimizer` | 提示词优化（非流式、无工具、system override） | ~120 |
| `AgentRunner` | Agent 模式多步执行（规划/工具回路） | ~250 |
| `Condenser` | 会话压缩/总结（可配置 summary model/system） | ~250 |
| `StorageService` | JSON 持久化（委托 importers） | ~300 |

## MCP/工具调用（Tool Calling）

### 1) 内置系统工具（无需外部 MCP Server）

当启用工具能力后，`core/tools/manager.py` 的 `McpManager.get_all_tools(include_mcp=True)` 会注入一组“本地系统工具”（工具名为 OpenAI tool schema 的 function name）。当 `include_mcp=False` 时，这些系统工具不会暴露给模型（避免纯聊天模式意外拿到工具）。

- 只读：`list_files` / `read_file` / `search_files`
- 编辑：`write_to_file` / `edit_file` / `builtin_filesystem_delete` / `apply_patch`
- 命令：`execute_command` / `builtin_python_exec`
- 其它：`manage_state`（会话 state 维护）、`skill`

这些工具用于支持多步 tool-call 回路：模型先请求工具 → 应用执行工具 → 将 `role=tool` 结果回填给模型继续推理。

### 1.5) 网络搜索工具（可选）

当启用搜索能力后，`McpManager.get_all_tools(include_search=True, ...)` 会额外注入：

- `builtin_web_search`

### 2) 外部 MCP Server（可选）

如果配置了 MCP servers（由 `StorageService` 读取本地配置），`McpManager` 会按需通过 `stdio_client + ClientSession` 临时连接：

- `list_tools()` 获取工具列表并以 `mcp__{server}__{tool}` 形式命名，避免与内置工具冲突
- `call_tool()` 执行工具并把结果回填为 `role=tool` 消息，交给下一轮 LLM 继续推理

## 设计原则

1. **单一职责**：每个模块只做一件事
2. **依赖倒置**：上层依赖下层抽象，不反向
3. **薄门面**：`LLMClient` 负责编排，细节下沉到 `core/llm/*`、`core/prompts/*`、`core/tools/*`
4. **避免循环导入**：纯工具放 `utils/`，Qt 工具放 `ui/utils/`
