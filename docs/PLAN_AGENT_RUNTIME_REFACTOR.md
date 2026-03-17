# Plan / Agent Runtime Refactor

## 目标

这轮重构的核心目标不是做表面清理，而是把 PyChat 的执行链统一成更接近 VS Code 风格的模式：

1. `/plan <content>` 不再只更新文档后返回 `Plan updated.`，而是直接进入真实运行链。
2. 显式技能命令 `/{skill}` 不再走单独的历史分支，而是与普通 prompt 共用同一条发送和执行路径。
3. UI 只负责采集输入和显示结果，命令解释、任务推进、附件处理、上下文拼装都下沉到 core。
4. 移除 alias 和兼容层，避免后续维护继续背历史包袱。

## 当前统一调用链

### 1. Slash Command 入口

入口位于 `core.commands`。

- 命令解析后返回 `CommandResult`
- 新的统一执行动作是 `CommandAction.PROMPT_RUN`
- `PROMPT_RUN` 负载类型是 `PromptInvocation`

`PromptInvocation` 负责携带：

- 最终要发送的内容 `content`
- 目标 mode `mode_slug`
- 需要提前写入会话状态的文档更新 `document_updates`
- 运行时元数据 `metadata`

这使 `/plan`、`/{skill}`、普通消息都能收敛到同一个消息发送链。

### 2. Presenter 桥接

`ui.presenters.conversation_presenter.ConversationPresenter` 现在只做三件事：

1. 处理 mode 切换
2. 把 `PromptInvocation` 写回当前会话状态
3. 通过正常发送链把内容交给 message presenter/runtime

原来 skill 专用的 presenter 分支已经移除。

### 3. Runtime / Task 执行

真正的执行仍由 core task runtime 推进。

- plan 模式仍是 plan 模式，只是不再停在命令层
- agent 模式仍通过 task loop 执行工具调用
- `attempt_completion` 的子任务结果不再被简单压扁成字符串

新增的 `SubTaskOutcome` 用来显式保存：

- 子任务文本结果
- completion 标记
- completion command

这样父任务可以准确判断子任务是否已经完成，而不是只拿到一段丢失语义的文本。

## `/plan <content>` 的新行为

旧行为：

1. 更新 `plan` 文档
2. 返回 `Plan updated.`
3. 停止，不再进入后续运行链

新行为：

1. 构造 `PromptInvocation`
2. 目标 mode 固定为 `plan`
3. 先把 `document_updates["plan"]` 写入当前会话状态
4. 再以普通用户消息的方式进入 plan 模式运行链

这样 plan 文档既是会话状态的一部分，也是后续 plan 模式推理的输入来源。

## 显式技能命令的新行为

旧行为：

- skills 走单独的 `SKILL_RUN` 动作
- presenter 有 skill 专用分支
- 命令层和消息发送链存在重复逻辑

新行为：

- 显式技能命令直接返回 `PROMPT_RUN`
- skill 元数据通过 `metadata["skill_run"]` 进入统一链路
- system prompt、message presenter、skills tool 仍可读取同一份 skill 元数据

这样 skill 不再是“特殊执行体系”，而是“带技能元数据的 prompt 运行”。

## Mode 与 Alias 策略

这轮改造明确移除了历史 alias：

- 命令 alias 已移除
- mode alias 已移除
- `architect -> plan` 不再保留兼容映射
- `.skills/` legacy 技能目录不再参与发现

当前策略是：

- 内建 mode 只认真实 slug
- 未知 mode 保留原 slug，由 mode 解析逻辑决定默认能力兜底
- skills 只从 `~/.PyChat/skills/` 与项目内 `.pychat/skills/` 发现

## 模块归属调整

### Attachments

图片编码逻辑已经从顶层 `utils.image_encoding` 移入 `core.attachments`。

原因：

- 该逻辑被 request builder、文件读取工具、UI 图片辅助同时使用
- 它本质上是附件运行时能力，不是通用 utils

### File Context

工作区文件树构造已经从 `utils.file_context` 移入 `core.context.file_context`。

原因：

- 该能力直接服务 prompt/context 组装
- 应和 system prompt / user context 位于同一领域边界

## UI 与 Core 边界

这轮还顺手清理了 UI/Core 重叠职责：

- `InputArea.build_run_policy()` 已移除
- `MessagePresenter` 直接使用 core 的 `build_run_policy(...)`
- 发送按钮统一为 icon 模式，不再保留冗余文本箭头状态

结果是：

- UI 只暴露输入状态
- core 决定运行策略
- presenter 只负责桥接，不再持有领域规则副本

## 验证结果

本轮改造完成后，已执行以下验证：

1. 静态错误扫描通过
2. `tests/test_skill_runtime.py` 全部通过，当前结果为 `25 passed`
3. 离屏模式下 `MainWindow` 可成功构造，输出 `MAIN_WINDOW_OK`

## 后续维护建议

后续如果继续清理架构，优先级建议如下：

1. 继续清理 README / ARCHITECTURE 中仍残留的旧 `controllers` 叙述
2. 检查 `memory` / `document` 命令是否还存在重复状态操作封装
3. 继续收紧 presenter 责任，保持 UI 不下沉业务判断