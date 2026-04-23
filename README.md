<div align="center">
   <img src="./assets/pycat.svg" width="128" height="128" alt="PyChat Logo" />

   <h1>PyChat</h1>

   <p><strong>基于 PyQt6 的跨平台桌面 LLM 聊天客户端</strong></p>

   <p>
      在体验上参考 Cherry Studio、Chatbox 一类桌面 AI 产品，
      聚焦于 <strong>多模型接入</strong>、<strong>对话组织</strong>、<strong>深度思考渲染</strong>
      与 <strong>MCP / Skills 扩展能力</strong>，让桌面端 AI 工作流更顺手、更清晰。
   </p>

   <p>
      <a href="./ARCHITECTURE.md">架构说明</a> ·
      <a href="./docs/PLAN_AGENT_RUNTIME_REFACTOR.md">运行时重构</a> ·
      <a href="./docs/ARCHITECTURE_REDESIGN.md">架构改造</a> ·
      <a href="./requirements.txt">依赖列表</a>
   </p>
</div>

<div align="center">
      <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&amp;logoColor=white" alt="Python 3.9+" />
      <img src="https://img.shields.io/badge/UI-PyQt6-41CD52?logo=qt&amp;logoColor=white" alt="PyQt6" />
      <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-6E56CF" alt="Platform" />
      <img src="https://img.shields.io/badge/MCP-Supported-7C3AED" alt="MCP Supported" />
      <img src="https://img.shields.io/badge/App-Desktop%20First-0EA5E9" alt="Desktop First" />
</div>

## ✨ 项目简介

PyChat 是一款面向桌面场景的 LLM 聊天客户端，目标是提供接近成熟产品的顺滑体验，同时保留 Python / PyQt 技术栈下易于扩展与维护的优势。

它适合以下使用方式：

- 在一个界面中统一管理多个模型供应商。
- 在长对话、多任务、多上下文场景下保持清晰的会话组织。
- 通过 MCP、技能文件、模式配置等机制扩展 AI 能力。
- 在本地桌面环境中获得更可控、更贴近生产使用的 AI 工作台体验。

## 🖼️ 界面预览

<table>
   <tr>
      <td align="center" width="68%">
         <img src="./assets/mainwindow.png" alt="PyChat 主界面" width="100%" />
         <br />
         <sub><strong>主界面</strong>：会话列表、消息流、任务 / 记忆 / 文档面板集中展示</sub>
      </td>
      <td align="center" width="32%">
         <img src="./assets/settings.png" alt="PyChat 设置界面" width="100%" />
         <br />
         <sub><strong>设置中心</strong>：模型服务商、模式配置、MCP、网络搜索、技能管理</sub>
      </td>
   </tr>
</table>

## 🌟 核心亮点

| 模块 | 说明 |
| --- | --- |
| 多模型供应商支持 | 支持 OpenAI、Claude（Anthropic）、Ollama、Google Gemini、DeepSeek 等多种 API / 协议接入。 |
| 深度思考渲染 | 自动解析并渲染 `<think>` / `<analysis>` 标签，支持流式展示思考过程。 |
| 对话与上下文管理 | 支持会话导入 / 导出、消息编辑、分支管理、图片上传与多模态交互。 |
| MCP / Skills 扩展 | 原生支持 Model Context Protocol，可接入本地工具、搜索服务与技能文件。 |
| 现代桌面体验 | 支持暗色 / 亮色主题、高 DPI 缩放适配、侧边栏会话树与清晰的信息布局。 |
| 性能可观测性 | 实时展示 Token 消耗速度（Tokens/sec）与响应时长，便于调优与观察。 |

## 🧩 功能概览

### 多模型与对话工作流

- 统一接入主流云端与本地模型。
- 支持更适合桌面端使用的会话管理方式。
- 兼顾日常聊天、写作、分析、代码辅助等场景。

### 扩展能力

- **MCP 服务器配置**：通过 `stdio` 方式连接外部工具或服务。
- **技能系统（Skills）**：支持复用型指令文件，扩展浏览器自动化等能力。
- **模式配置**：为不同任务切换不同运行模式或策略。

### 数据与展示能力

- 支持多种对话导入格式。
- Markdown、代码块与结构化内容展示更清晰。
- 样式文件位于 `assets/styles/`，可进一步自定义界面外观。

## 🏗️ 架构设计

项目采用分层架构，便于维护与后续重构：

- **`ui/`**：纯表现层，负责窗口、组件、输入状态采集与交互转发。
- **`core/`**：运行时核心，负责命令分发、任务循环、prompt 组装、skills、attachments、上下文构建等。
- **`services/`**：应用服务层，负责会话持久化、Provider 管理、搜索 / MCP 服务编排等。
- **`models/`**：数据模型层，保存 Conversation、Provider、State 等结构。
- **`utils/`**：通用辅助逻辑，仅保留真正与业务领域无强耦合的工具代码。

更多说明请参考：

- [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- [`docs/PLAN_AGENT_RUNTIME_REFACTOR.md`](./docs/PLAN_AGENT_RUNTIME_REFACTOR.md)
- [`docs/ARCHITECTURE_REDESIGN.md`](./docs/ARCHITECTURE_REDESIGN.md)

## 🚀 快速开始

### 环境要求

- Python 3.9+
- Windows / macOS / Linux

### 安装与运行

```bash
git clone <repository-url>
cd pychat
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

如果你只是想尽快体验，核心启动路径非常直接：安装依赖，然后执行 `python main.py` 即可。没有花里胡哨，主打一个马上开聊。

## 📁 目录速览

```text
pychat/
├─ assets/        # 图标、截图、样式资源
├─ core/          # 运行时核心逻辑
├─ docs/          # 设计文档、重构规划、调研资料
├─ models/        # 数据模型
├─ services/      # 应用服务与集成层
├─ tests/         # 测试代码
├─ ui/            # 界面层
├─ utils/         # 通用工具
└─ main.py        # 应用入口
```

## ⚙️ 重点说明

### MCP 服务器配置

你可以在设置中添加 MCP 服务器。PyChat 支持通过 `stdio` 与 MCP 服务通信，从而把网络搜索、本地文件操作、外部工具调用等能力接入到对话流程中。

### 对话导入

当前支持多种历史记录导入形式，包括：

- **ChatGPT Export**：导入官方导出的 JSON 数据包。
- **OpenAI Payload**：基于 API 请求载荷生成对话。
- **Conversation JSON**：项目自定义备份格式。

### 样式定制

界面样式资源主要位于 `assets/styles/`。如果你希望继续向 Cherry Studio 风格靠拢，或者做出自己的品牌化外观，这里就是你的主战场。

## 🤝 贡献指南

欢迎参与改进 PyChat。建议在提交代码前先了解当前的分层约束：

1. 遵循分层依赖规则，避免出现反向引用。
2. 新增 Provider 时，优先在 `services/llm/` 扩展对应请求构建逻辑。
3. 保持 `models/` 层纯净，不引入 I/O 或 UI 依赖。
4. 对涉及运行时与架构的改动，建议同步更新相应设计文档。

如果你准备开始动手，先读一遍 `ARCHITECTURE.md`，会少踩很多坑——这不是玄学，是经验值。
