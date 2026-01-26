# PyChat 架构与代码组织

## 当前分层

```
pychat/
├── models/              # 纯数据模型（无外部依赖）
│   ├── conversation.py  # Conversation, Message, ConversationStreamState
│   ├── provider.py      # Provider 模型
│   ├── mcp_server.py    # MCP 服务器配置
│   └── search_config.py # 搜索配置
│
├── utils/               # 纯工具函数（无 UI/services 依赖）
│   └── image_encoding.py # encode_image_file_to_data_url
│
├── services/            # 业务逻辑层
│   ├── chat_service.py  # LLM 请求编排（薄门面）
│   ├── storage_service.py # 本地 JSON 持久化
│   ├── provider_service.py # Provider 管理
│   ├── mcp_manager.py   # MCP + 搜索工具管理
│   ├── search_service.py # 网络搜索服务 (Tavily/Google/SearXNG)
│   ├── llm/             # LLM 基础设施
│   │   ├── request_builder.py # 构建 API 请求
│   │   ├── http_utils.py      # HTTP/SSE 工具
│   │   └── thinking_parser.py # 思考标签解析
│   └── importers/       # 导入格式解析
│       ├── parse.py     # 统一入口
│       └── *.py         # 各格式解析器
│
├── controllers/         # 业务编排层
│   └── stream_manager.py # 并发流式管理
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
models  ←─ utils ←─ services ←─ controllers ←─ ui
           │              │
           └──────────────┘  （services.llm 使用 utils）
```

**规则**：上层可引用下层，禁止反向引用。utils 作为最底层，任何层都可引用。

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
  - 后台线程创建 event loop 调用 `ChatService.send_message()`
  - 通过 Qt signal 把 token/thinking/complete/error 安全地回传主线程

### 4) 切换会话时的恢复

`Sidebar.conversation_selected` → `MainWindow._on_conversation_selected()`：
- `StorageService.load_conversation()`
- `ChatView.load_conversation()`
- 如果该会话仍在生成：从 `StreamManager.get_state()` 取缓存文本，调用 `ChatView.restore_streaming_state()`

## 模块职责

| 模块 | 职责 | 行数约 |
|-----|-----|-------|
| `ChatService` | LLM 请求编排（薄门面） | ~280 |
| `request_builder` | 构建 API messages/body | ~90 |
| `http_utils` | HTTP 错误格式化、SSE 解析 | ~100 |
| `thinking_parser` | `<think>`/`<analysis>` 标签提取 | ~80 |
| `StreamManager` | 并发流式状态管理 | ~200 |
| `StorageService` | JSON 持久化（委托 importers） | ~300 |

## MCP/工具调用（Tool Calling）

### 1) 内置默认工具（无需外部 MCP Server）

当 UI 里启用 `MCP` 开关后，`McpManager.get_all_tools(include_mcp=True)` 会自动注入一组内置工具：

- `builtin_filesystem_ls`：列出工作区目录内容（支持递归/限制条目）
- `builtin_filesystem_read`：读取工作区内文件（限制字节数）
- `builtin_filesystem_grep`：在工作区内按正则检索（可选 glob 过滤）
- `builtin_python_exec`：本地执行 Python 代码（带超时，返回 stdout/stderr）

这些工具用于实现“默认 MCP 系统能力”，并支持多步 tool-call（模型可先 ls 再 read/grep，再总结）。

### 2) 外部 MCP Server（可选）

如果配置了 `mcp_servers.json`，`McpManager` 会按需通过 `stdio_client + ClientSession` 临时连接：

- `list_tools()` 获取工具列表并以 `mcp__{server}__{tool}` 形式命名，避免与内置工具冲突
- `call_tool()` 执行工具并把结果回填为 `role=tool` 消息，交给下一轮 LLM 继续推理

## 设计原则

1. **单一职责**：每个模块只做一件事
2. **依赖倒置**：上层依赖下层抽象，不反向
3. **薄门面**：`ChatService` 只编排，实现细节在子模块
4. **避免循环导入**：纯工具放 `utils/`，Qt 工具放 `ui/utils/`
