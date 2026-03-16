# PyChat 架构重设计方案

## 1. 目标

本方案的目标不是在现有实现上继续堆补丁，而是把 PyChat 收敛成一套清晰、可维护、可扩展的运行时架构：

- UI 只负责展示与交互，不再承载业务编排。
- Chat、Agent、Plan、Code 等模式共享同一条执行主干，只在策略上不同。
- Prompt 组装、历史压缩、工具调用、状态更新、持久化边界都各自有唯一责任归属。
- 全局资源与工作区资源分层明确，避免 `~/.PyChat`、工作区目录、消息 JSON 三处重复持有状态。

## 2. 参考结论

### 2.1 VS Code Copilot 的可借鉴点

从 `temp/vscode-copilot-chat-main` 可以提炼出四个关键原则：

1. System prompt 只承载稳定规则、能力说明、格式规范，不承载易变运行时上下文。
2. 环境信息、最近历史、压缩总结是独立装配的 prompt section，而不是把环境信息硬塞进最新一条 user message。
3. 历史压缩有专门的 summarization prompt，强调最近执行命令、工具结果、当前工作状态的结构化保留。
4. 计划、进度、工具前置说明、最终回答格式都是统一规则，不散落在业务代码里。

### 2.2 RooCode 的可借鉴点

从 `temp/roocode` 可以提炼出四个关键原则：

1. Webview/UI 与任务循环分离，控制器只做桥接。
2. Tool registry、prompt engine、task loop、MCP hub 是独立子系统。
3. 工具调用协议有专门的防御层，而不是边流式解析边拼消息。
4. 模式系统本质是策略配置，不应该演变成多套执行引擎。

## 3. 当前 PyChat 的核心问题

### 3.1 Prompt 责任混乱

当前请求样本 `debug_request_1773381327.json` 表明：

- `environment_info` 和 `workspace_info` 被直接包进第一条 user message。
- 工具调用往返大量混在 messages 中。
- 历史一长之后，模型视角中的“真实用户意图”会被工具调用噪音和上下文包装稀释。

这与 VS Code Copilot 的做法不同。Copilot 会显式保留：

- 稳定 system rules
- 独立环境信息
- 最近完整历史
- 历史总结

而不是把运行时上下文混在 user content 里。

### 3.2 历史压缩粒度错误

Agent 模式真正要保留的是：

- 最近 3 条完整 user-led turn blocks
- 1 份结构化 summary

这里的“完整历史”是以 user turn 为边界，而不是简单按消息条数，也不是把 tool message 当成普通聊天历史。工具调用属于执行痕迹，应保留其摘要，而不是在窗口内无限挤占真实对话。

### 3.3 执行引擎分叉

当前 Chat、Agent、UI runtime、LLM client 之间仍存在多处重复职责：

- 谁负责选 history
- 谁负责加 system prompt
- 谁负责 tool loop
- 谁负责状态同步
- 谁负责重试

只要这些责任散在多个模块里，行为就会继续漂移。

### 3.4 持久化边界不清晰

当前项目同时存在两类资源：

- 全局用户资源：modes、skills、providers、全局 conversations
- 工作区会话资源：summary、plan、memory、todo、会话执行痕迹

此前的问题是它们被散落在 roaming 目录、`~/.PyChat`、以及会话 JSON 内部。重设计后应该明确分层。

## 4. 概念模型

这些概念必须严格区分：

- `task`: 一次独立执行单元，可对应主任务或子任务。
- `todo`: 当前 task 的可执行步骤列表，强调短周期进度。
- `plan`: 当前 task 的长期工作文档，强调目标、阶段、方法。
- `summary`: 历史压缩结果，服务于上下文窗口管理。
- `memory`: 可跨多轮复用的稳定事实，不等于 summary。

推荐约束：

- 每个会话始终存在 `plan` 文档。
- 每轮执行前后都允许更新 `todo`。
- 重要分析产物写入 `documents/content.md` 或其它命名文档，而不是只留在聊天消息里。
- `summary` 只由压缩器维护，业务逻辑不直接写。

## 5. 目标架构

### 5.1 分层

推荐目录收敛为：

- `ui/`: QWidget、dialog、presenter、viewmodel；不直接编排 LLM/tool loop。
- `core/runtime/`: 统一执行引擎。
- `core/prompts/`: prompt section、assembler、summary prompt。
- `core/tools/`: tool registry、权限、执行器、协议防御。
- `core/modes/`: 模式定义与策略映射。
- `core/skills/`: skill discovery、activation、resource loading。
- `core/tasks/`: 多 agent/子任务编排。
- `services/`: provider/storage/import 等基础服务。
- `models/`: Conversation、Message、SessionState、Task 等纯数据对象。

### 5.2 统一执行主干

引入统一 `TurnEngine`：

- 输入：conversation、mode policy、provider、runtime flags
- 输出：统一事件流 `TurnEvent`

建议事件类型：

- `text_delta`
- `thinking_delta`
- `tool_call`
- `tool_result`
- `state_patch`
- `turn_complete`
- `turn_error`
- `retry`

UI、CLI、TUI、Webhook 注入层都只订阅这些事件，不自己拼执行流程。

### 5.3 Prompt 组装

Prompt 必须固定为四段：

1. `system rules`: 模式规则、工具说明、安全与输出规范。
2. `environment block`: OS、cwd、workspace tree、当前文件、运行时能力。
3. `summary block`: 历史压缩摘要、最近关键工具结果摘要。
4. `recent history`: 最近 3 条完整 user-led turn blocks。

关键约束：

- 不再把 `environment_info` 包进真实 user message。
- tool result 进入 recent history 时应经过协议规整；超长输出仅以摘要形式出现。
- system prompt 不再承载 `conversation-summary` 这类易变内容。

### 5.4 历史压缩

压缩器应遵守以下规则：

- 以 user turn block 为单位保留最近 3 轮完整历史。
- 旧轮次压缩为 `summary`。
- 工具调用不参与“最近 3 轮”的计数，但其关键结论进入 summary。
- 最近一次失败命令、最近一次关键工具结果、当前未完成任务状态必须进入 summary。

### 5.5 Tool 系统

工具体系拆成四层：

1. `ToolCatalog`: schema 与展示信息。
2. `ToolPolicy`: 权限、模式开关、用户授权、allowlist/denylist。
3. `ToolExecutor`: 实际执行，产出标准化结果。
4. `ToolProtocolGuard`: 对齐 `tool_call_id`、去重、补缺、异常规整。

工具要分组，而不是散列启停：

- `read`
- `edit`
- `command`
- `search`
- `browser`
- `mcp`
- `state`
- `task`

模式只声明允许哪些 group，执行时再由 `ToolPolicy` 做最终裁决。

### 5.6 Shell / 命令执行

Shell 工具必须支持会话化：

- `shell_start`
- `shell_status`
- `shell_logs`
- `shell_wait`
- `shell_kill`

并把后台 shell 元数据持久化到工作区会话目录，便于后续继续操作，而不是每轮都丢失上下文。

### 5.7 Skill 系统

Skill 应采用渐进式披露模型：

1. 启动时仅暴露 metadata：`name`、`description`、`policy`、`scope`。
2. 激活后再加载 `SKILL.md` 正文。
3. 按需读取 `references/`、`templates/`、`scripts/`。

推荐作用域：

- 全局 skill：`~/.PyChat/skills/<name>/SKILL.md`
- 工作区 skill：`<workspace>/.pychat/skills/<name>/SKILL.md`

不建议把 skill 正文直接长期注入 system prompt。应只注入可发现 metadata，正文在激活时以 instruction block 或子任务 prompt 注入。

### 5.8 模式系统

模式本质是 `TurnPolicy` 预设，而不是多套引擎：

- `chat`: 少工具、少轮次、偏回答。
- `plan`: 强制维护 plan/todo，尽量少改代码。
- `code`: 允许读写文件、运行测试，强调精确实现。
- `agent`: 允许多轮 tool loop、重试、子任务。
- `architect`: 强制输出设计文档与边界分析。

每个模式只定义：

- 可用 tool groups
- 默认重试策略
- 是否允许子任务
- 是否要求 plan/todo
- 输出风格

### 5.9 多 Agent 协同

引入 `TaskGraph`：

- 主任务保留总目标与全局 context。
- 子任务只接收必要 summary、plan 片段与 scoped tool policy。
- 子任务结果回流为结构化 artifact，而不是一串自然语言消息。

建议最小子任务类型：

- `ExploreTask`
- `PlanTask`
- `ImplementTask`
- `ReviewTask`

### 5.10 持久化边界

持久化分成两层：

- 全局层：`~/.PyChat/`
  - `skills/`
  - `modes.json`
  - `providers.json`
  - `conversations/`
  - `mcp_servers.json`

- 工作区层：`<workspace>/.pychat/`
  - `skills/`
  - `sessions/<conversation-id>/meta.json`
  - `sessions/<conversation-id>/state.json`
  - `sessions/<conversation-id>/summary.md`
  - `sessions/<conversation-id>/tasks.json`
  - `sessions/<conversation-id>/memory.json`
  - `sessions/<conversation-id>/documents/*.md`
  - `sessions/<conversation-id>/shell/*.json`

结论：

- 用户级可复用资产放 `~/.PyChat`。
- 工作区会话资产放 `.pychat`。
- 不再引入第二套 roaming 根目录。

## 6. 与当前代码的对应改造方向

### 已经收口的部分

- `/compact`、`/clear`、`/skill <name>` 的展示 metadata 已集中到 command registry。
- 三段式上下文已开始从 `system + runtime wrapped user` 转向显式 assembler。
- 会话状态镜像已开始落到独立 session 目录。
- LLM 重试已具备独立执行模块雏形。

### 下一步必须继续收口的部分

1. 把 `core/task/executor.py`、`core/task/tool_executor.py` 与 UI runtime 继续统一到 `TurnEngine`。
2. 把 `services/chat_service.py` 进一步降级为 facade，不再参与上下文策略。
3. 为 Playwright/MCP 建立会话级 runtime handle registry，避免每轮结束就丢浏览器状态。
4. 为 Shell 工具增加会话索引与日志持久化。
5. 把 summary 生成、保留最近 3 轮、tool result 摘要化做成单一规则入口。

## 7. 迁移建议

### Phase 1

- 固化 `TurnPolicy`
- 固化 `PromptAssembler`
- 固化 `ToolProtocolGuard`
- 保持现有 UI，不动界面布局

### Phase 2

- 抽出 `TurnEngine`
- Chat 与 Agent 共用事件流
- 模式切换全面策略化

### Phase 3

- 引入 `TaskGraph` 与子任务协作
- CLI/TUI/Webhook 复用同一 runtime
- 清理旧模块与临时兼容层

## 8. 最终结论

PyChat 未来应围绕一个中心收敛：

> 单一执行主干 + 明确 prompt 分层 + 策略化模式系统 + 会话级持久化 + 渐进式 skill/tool 体系。

只要继续沿这个方向推进，`#`、`@`、`/`、skill、mode、MCP、shell、多 agent 都不会再演变成各写各的分支能力，而会落回同一套清晰的运行时结构。