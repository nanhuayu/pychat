# PyChat

PyChat 是一款基于 PyQt6 开发的跨平台桌面 LLM 聊天客户端。它旨在提供类似 Cherry Studio 或 Chatbox 的流畅体验，同时集成了强大的模型管理、对话管理和扩展功能。

## ✨ 核心特性

- **多模型供应商支持**：支持 OpenAI, Claude (Anthropic), Ollama, Google Gemini, DeepSeek 等多种 API 协议。
- **深度思考 (Deep Thinking) 支持**：自动解析并渲染 `<think>` 或 `<analysis>` 标签，支持流式展示思考过程。
- **MCP (Model Context Protocol) 集成**：原生支持 Model Context Protocol，允许 LLM 调用本地工具和搜索服务。
- **先进的对话管理**：
    - 支持对话导入/导出（支持 ChatGPT 导出格式、OpenAI Payload 等）。
    - 消息编辑与分支管理。
    - 图片上传与多模态交互。
- **性能监控**：实时显示 Token 消耗速度 (Tokens/sec) 和响应时长。
- **现代化 UI**：
    - 基于 QSS 的高品质主题（支持暗黑/明亮模式）。
    - 高 DPI 缩放适配。
    - 侧边栏对话树管理。

## 🏗️ 架构设计

项目采用分层架构设计，确保代码的可维护性和可扩展性：

- **`ui/`**: 纯表现层。负责窗口、组件、输入状态采集，以及将用户操作转发给 presenter/runtime。
- **`core/`**: 运行时核心。负责命令分发、mode/policy、任务循环、prompt 组装、skills、attachments、上下文构建。
- **`services/`**: 应用服务层。负责会话持久化、Provider 管理、搜索/MCP 服务编排等。
- **`models/`**: 数据模型层。保存 Conversation、Provider、State 等结构。
- **`utils/`**: 仅保留真正通用且不属于具体领域的辅助逻辑。

详细架构说明请参考 [ARCHITECTURE.md](./ARCHITECTURE.md) 和 [docs/PLAN_AGENT_RUNTIME_REFACTOR.md](./docs/PLAN_AGENT_RUNTIME_REFACTOR.md)。

## 🚀 快速开始

### 环境要求
- Python 3.9+
- Windows / macOS / Linux

### 安装步骤

1. **克隆项目**
   ```bash
   git clone <repository-url>
   cd pychat
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **运行应用**
   ```bash
   python main.py
   ```

## 🛠️ 功能详解

### MCP 服务器配置
在设置中可以添加 MCP 服务器。PyChat 支持通过 `stdio` 方式与 MCP 服务器通信，扩展 AI 的能力（如网络搜索、本地文件操作等）。

### 对话导入
支持从多种格式导入对话历史：
- **ChatGPT Export**: 导入官方导出的 JSON 数据包。
- **OpenAI Payload**: 直接从 API 请求载荷创建对话。
- **Conversation JSON**: 项目自定义的备份格式。

### 主题定制
样式文件存储在 `assets/styles/` 目录下，可以通过修改 `.qss` 文件来自定义界面外观。

## 🤝 贡献指南

1. 遵循分层依赖规则：`ui -> controllers -> services -> models`。禁止反向引用。
2. 新增 Provider 时，请在 `services/llm/` 目录下扩展对应的请求构建逻辑。
3. 保持 `models/` 层的纯净，不引入任何 I/O 或 UI 依赖。

## 📄 开源协议

[MIT License](LICENSE) (如果有)
