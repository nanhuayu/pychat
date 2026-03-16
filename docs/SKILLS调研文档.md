下面给你一份**偏“架构设计 + 规范设计 + 运行时实现”**的深度报告。我会把它分成两层：

1. **可移植的通用 Skill 规范**：适合你自己做一个 `~/.agent/skills` / 项目级 `skills/` 的 agent 系统。  
2. **Claude/Anthropic 生态的具体映射**：因为你提到的 `SKILL.md`、目录式 skill、同目录下 `references/templates/scripts` 等，实际上和 Anthropic 当前公开的 Agent Skills 体系高度一致；官方已经把它做成了 open standard，并在 Claude Code、Claude API、Agent SDK 里分别落地了。

---

# 一、先给结论

**Skill 不是“一个 prompt 文件”这么简单。**更准确地说，它是一个**可发现、可按需加载、可组合、可执行、可版本化**的“能力包”。它通常以一个目录存在，核心入口是 `SKILL.md`，里面分成两部分：

- **YAML frontmatter**：给运行时/模型看的元数据，重点是“这个 skill 是什么、什么时候该用”；
- **Markdown body**：真正的操作说明、流程、约束、样例、边界条件。

这类设计最核心的思想不是“把所有知识一次性塞给模型”，而是**progressive disclosure（渐进式披露）**：

- 启动时只暴露所有 skill 的少量元数据；
- 当某个 skill 被判定相关时，再加载完整 `SKILL.md`；
- 当 `SKILL.md` 再引用 `references/`、`templates/`、`scripts/` 等时，才继续按需读取或执行。

所以，如果你要做自己的 agent，最佳实践不是把 skill 当“静态大 prompt”，而是把它当成：

> **一份可索引的元数据 + 一份可延迟装载的执行手册 + 一组可选资源文件 + 一套可控权限边界。**

---

# 二、Skill 在 Agent 体系里的位置

一个很重要的概念区分是：

- **Tool / MCP**：提供“能力接口”，比如读文件、查网页、调数据库、执行脚本；
- **Skill**：提供“什么时候用这些能力、用什么步骤、遵守什么约束、输出成什么格式”的**工作流知识**。Anthropic 官方材料把它比喻成：MCP/工具像“厨房和设备”，Skill 像“菜谱和做法”。

所以在系统分层上，比较合理的关系是：

- **LLM**：负责理解任务与规划；
- **Tool/MCP**：负责执行外部动作；
- **Skill**：负责把某类任务的知识和流程打包成可复用能力；
- **Runtime/Orchestrator**：负责发现、选择、加载、执行 skill。

---

# 三、目录应该怎么设计

## 3.1 你自己的通用设计：建议这样做

如果你做一个中立的 agent runtime，我建议采用这样的搜索路径：

```text
全局技能库:
~/.agent/skills/<skill_name>/SKILL.md

项目技能库:
<project>/.agent/skills/<skill_name>/SKILL.md
或
<project>/skills/<skill_name>/SKILL.md
```

这是**我建议的通用实现**，因为用户级 skill 和项目级 skill 的分层最自然，也方便团队共享和个人偏好分离。

一个推荐目录长这样：

```text
~/.agent/skills/
  api-design/
    SKILL.md
    references/
      error-format.md
      pagination.md
    templates/
      openapi-template.yaml
    scripts/
      validate_openapi.py
    assets/
      example-response.json
```

这里要注意：**真正的 open SKILL.md 规范只强制要求“目录 + `SKILL.md`”**；`scripts/`、`references/`、`assets/` 是官方推荐约定，但并不是唯一可能目录。Claude Code 文档也明确允许 skill 目录下放更多辅助文件，只要你在 `SKILL.md` 里把它们说明白。

## 3.2 Claude 生态里的实际路径

如果你想兼容 Claude 当前实现，真实路径是：

- 用户级：`~/.claude/skills/<skill-name>/SKILL.md`
- 项目级：`.claude/skills/<skill-name>/SKILL.md`
- 插件级：`<plugin>/skills/<skill-name>/SKILL.md`

Claude Code 还支持在嵌套子目录里自动发现 `.claude/skills/`，适合 monorepo。

Claude Agent SDK 也是从文件系统加载 skill，但需要你显式打开：

- `setting_sources=["user", "project"]`
- `allowed_tools=["Skill", ...]`

否则 SDK 默认**不会**加载文件系统 skill。

---

# 四、SKILL.md 到底有什么“特殊格式”

这里要分成两层说：**标准层**和**产品扩展层**。

---

## 4.1 标准层：最小可移植格式

open Agent Skills 规范要求 `SKILL.md` 是：

1. **YAML frontmatter**
2. **Markdown 正文**

最小例子类似这样：

```md
---
name: pdf-processing
description: Extract text and tables from PDF files, fill forms, and merge documents. Use when handling PDFs, forms, or document extraction.
---

# PDF Processing

## Steps
1. Detect whether the PDF is text-based or scanned.
2. For text PDFs, extract text and tables.
3. For forms, load form-filling rules from references/FORMS.md.
4. Validate output format before saving.

## References
- references/FORMS.md
- references/REFERENCE.md
```

按 open spec，`name` 和 `description` 是核心字段；还支持 `license`、`compatibility`、`metadata`，以及实验性的 `allowed-tools`。Markdown body 没有限死章节格式，但官方建议至少包含：**步骤、输入输出样例、边界情况**。

---

## 4.2 常见辅助目录

规范和官方文档里最常见的辅助内容有：

- `scripts/`：可执行脚本；
- `references/`：按需阅读的参考资料；
- `assets/` 或 `templates/`：模板、静态资源、示例文件。

它们的职责应该分得很清楚：

- **SKILL.md**：概览 + 导航 + 核心步骤；
- **references/**：长文档、规则表、schema、FAQ；
- **templates/**：让模型产出时套用的模板；
- **scripts/**：交给运行时执行的程序，而不是让模型“读懂全部代码”。

---

## 4.3 Claude Code 的扩展字段

Claude Code 在 open standard 上加了一些很实用的 frontmatter 扩展，包括：

- `argument-hint`
- `disable-model-invocation`
- `user-invocable`
- `allowed-tools`
- `model`
- `context`
- `agent`
- `hooks`

这些字段让 skill 不再只是“说明书”，而变成**带调度策略的能力单元**。比如：

- `disable-model-invocation: true`：模型不能自动触发，只能用户手动 `/skill-name` 触发；
- `user-invocable: false`：用户菜单里不显示，但模型可自动使用；
- `context: fork` + `agent: Explore`：把 skill 放到一个隔离 subagent 里执行。

---

# 五、为什么说 SKILL.md 不是普通 Markdown，而是“特殊文档”

## 5.1 frontmatter 不是给人看的，它首先是给 runtime / 模型看的

在 Agent Skills 设计里，**frontmatter 的元数据会先进入系统级上下文**，用于发现与路由；Anthropic 的官方指南甚至明确提醒：frontmatter 出现在系统提示中，因此要防止恶意注入。也因此，当前官方规则会限制 `name` / `description`，例如不能带 XML 标签，并避免使用保留词如 `anthropic`、`claude`。

所以从系统设计角度看，`SKILL.md` 至少一分为二：

- **frontmatter = 发现/路由/权限/调度元数据**
- **body = 被选择后才加载的任务知识**

---

## 5.2 `description` 是发现机制的核心，不是简介装饰

官方最佳实践反复强调：

- `description` 要写清楚 **做什么**；
- 还要写清楚 **什么时候用**；
- 最好包含用户可能说出的关键词、文件类型、场景触发词；
- 甚至建议用**第三人称**，因为它会被注入系统提示。

这意味着 skill 的发现并不是“看目录名猜一下”，而是靠一条高质量 description 做**语义匹配/路由**。如果你自己做 runtime，description 质量会直接决定 skill 命中率。

---

## 5.3 它天生是“渐进式披露文档”

官方规范与文档都建议：

- metadata 只占很少 token；
- 完整 `SKILL.md` 被激活时再读；
- `references/`、`assets/`、`scripts/` 只在需要时再读/执行；
- `SKILL.md` 最好控制在 500 行以内，长材料拆出去。

这和传统 prompt engineering 很不一样：  
传统 prompt 常常是**一次性全塞**；  
skill 更像**索引 + 延迟展开**。

---

# 六、如何把 Skill “传递给大模型”

这是你问题里最关键的一段。实际上至少有四种传递路径。

---

## 6.1 路径 A：本地文件系统型 agent（最适合你自己实现）

这是你说的 `~/.agent/skills` / 项目 `skills/` 最自然的方式。

### 运行时应做的事

1. **扫描 skill 根目录**
2. 只解析每个 `SKILL.md` 的 frontmatter
3. 构建 skill registry：
   - `name`
   - `description`
   - `path`
   - `scope`（global/project）
   - `version/hash`
   - `capabilities`
4. 在会话启动时，把**skill 元数据列表**给模型，而不是把所有 skill 正文全塞进去
5. 当模型判断某个 skill 相关，或者用户显式调用时，再加载完整 `SKILL.md`
6. 如果 `SKILL.md` 里引用 `references/*`、`templates/*`、`scripts/*`，再按需读取或执行。这个过程和 Claude 当前的 regular session 机制基本一致。

### 一个通用的内部数据结构

我建议你在 runtime 里把一个 skill 编译成：

```json
{
  "id": "api-design",
  "name": "api-design",
  "description": "Applies API conventions when designing or modifying HTTP endpoints...",
  "scope": "project",
  "path": "/repo/.agent/skills/api-design",
  "entrypoint": "SKILL.md",
  "resources": {
    "references": ["references/error-format.md", "references/pagination.md"],
    "templates": ["templates/openapi.yaml"],
    "scripts": ["scripts/validate_openapi.py"]
  },
  "policy": {
    "user_invocable": true,
    "model_invocable": true,
    "allowed_tools": ["Read", "Glob", "Grep"]
  }
}
```

这部分是**我的实现建议**；它和 Claude/Open Skill 的思路一致，但更适合作为你自己的 agent 内部表示。其依据是：运行时先看 metadata，正文和辅助文件在后续阶段按需装载。

---

## 6.2 路径 B：作为 API 对象上传，再在消息里引用

如果你走的是 Claude API 当前做法，流程是：

1. `POST /v1/skills` 上传一个目录包；
2. 包里必须有顶层 `SKILL.md`；
3. 发 `messages` 请求时，在 `container.skills` 里列出要挂载的 skill；
4. 同时必须开启 **code execution**，因为 skill 运行在 code execution 环境里。

官方 API 里的请求形态大致是：

```json
{
  "model": "claude-opus-4-6",
  "container": {
    "skills": [
      {
        "type": "custom",
        "skill_id": "skill_xxx",
        "version": "latest"
      }
    ]
  },
  "messages": [
    {"role": "user", "content": "Generate the report"}
  ],
  "tools": [
    {"type": "code_execution_20250825", "name": "code_execution"}
  ]
}
```

这类 skill 在 API 里有几个关键事实：

- 通过 `container.skills` 挂载；
- 需要 `code-execution-2025-08-25` 和 `skills-2025-10-02` 等 beta 能力；
- skill 文件会被复制进容器里的 `/skills/{directory}/`；
- Claude 先看到 metadata，再在相关时自动使用；
- 每次请求最多 8 个 skills；
- 上传总大小目前上限是 8MB。

如果 skill 生成文档文件，响应会返回 `file_id`，你需要再走 Files API 下载；长任务还可能返回 `pause_turn`，要求你复用 container 续跑。

---

## 6.3 路径 C：把 skill 预注入 subagent

Claude 的 subagent 机制支持在 frontmatter 里写：

```yaml
skills:
  - api-conventions
  - error-handling-patterns
```

这时的语义不是“让 subagent 以后自己发现它们”，而是**在 subagent 启动时直接把这些 skill 的完整内容注入它的上下文**。官方文档明确说：这是 full skill content injected at startup，而且 subagent 不会继承父会话的 skills，必须显式列出来。

这给你一个很重要的架构启发：

- **普通会话**：skill 是“可发现、按需加载”的；
- **预装 subagent**：skill 是“启动时即内化到子代理系统提示”的。

---

## 6.4 路径 D：skill 自己声明“在子代理里执行”

Claude Code 还支持在 skill frontmatter 中写：

```yaml
context: fork
agent: Explore
```

这表示：**当前 skill 不是直接在主会话里 inline 运行，而是在一个隔离的 subagent 环境里执行**；此时 `SKILL.md` 的正文就变成那个 subagent 的任务提示。官方还明确说明：这种 fork skill **不继承你的对话历史**。

对你自己做 agent 很有价值，因为这意味着你完全可以把 skill 分成两类：

1. **Knowledge skill**：补充上下文，内联生效；
2. **Action skill**：生成一个子任务，交给隔离 agent 执行。

---

# 七、一个通用 Agent 的推荐调用链路

下面是我建议你实现的**标准 skill runtime**。

## 7.1 启动阶段：只建索引，不灌全文

```text
scan skill roots
-> parse SKILL.md frontmatter
-> validate schema
-> build registry
-> inject only metadata catalog into model-visible context
```

为什么要这么做？因为官方 skill 体系的核心就是：**元数据始终可见，正文与资源按需加载**。

---

## 7.2 选择阶段：两级路由

我建议用“两级 skill 选择”：

### 第一级：运行时预筛选
根据：
- 用户 query
- 文件类型
- 当前工作目录
- 最近工具使用
- embedding / keyword / rules

先从几百个 skill 里筛出 3~10 个候选。

### 第二级：交给模型决定
把候选 skill 的简短元数据给模型，让模型决定：

- 不用任何 skill
- 用一个 skill
- 组合多个 skills
- 用 inline skill 还是 fork skill

这是对官方“description 决定何时选中”的一种工程化实现。

---

## 7.3 激活阶段：装载正文，不要一次把 references 全塞进去

激活某个 skill 后：

1. 读取 `SKILL.md` 正文
2. 解析其中引用的 `references/*`、`templates/*`、`scripts/*`
3. **只加载当前步骤明确需要的文件**
4. 若需执行脚本，则通过工具层执行，不必先把整个脚本源码灌进上下文

这和官方文档中的推荐用法完全一致：supporting files 应由 `SKILL.md` 导航；脚本是执行型资源，不应被当成长上下文材料整体加载。

---

## 7.4 执行阶段：把 skill 当成“受控 prompt 片段”而不是裸文本

我建议 skill 激活后，不要简单粗暴地把 `SKILL.md` 当 user message 拼接进去，而是拆成下面三类：

### A. 发现层元数据
进入 system / developer 层 catalog，例如：

```json
{"name":"api-design","description":"..."}
```

### B. 激活层指令
把 `SKILL.md` 正文作为**高优先级工作指令片段**注入当前任务上下文。

### C. 资源层引用
按需装入 `references/*` 内容，或执行 `scripts/*`，然后把结果回填给模型。

这样做的好处是，你能在 runtime 层显式控制：
- 哪部分是 discovery
- 哪部分是 instruction
- 哪部分是 execution artifact

这是比“整文件拼 prompt”成熟得多的 agent 设计。其依据是官方的 progressive disclosure 与 code-execution/filesystem loading 模型。

---

# 八、SKILL.md 推荐写法：给你一份可直接落地的模板

下面这份模板，我建议你作为**你自己的 `.agent/skills` 标准**。

## 8.1 可移植基础模板

```md
---
name: api-design
description: Applies API design conventions for HTTP endpoints. Use when creating, modifying, or reviewing REST or RPC APIs, especially when request validation, pagination, or error formats are involved.
license: Proprietary
compatibility: Requires filesystem access and optional Python 3 for validation scripts
metadata:
  owner: platform-team
  version: "1.2.0"
---

# API Design Skill

## Purpose
Help the agent design or review APIs according to team conventions.

## When to use
Use this skill when:
- creating new endpoints
- changing request/response schemas
- reviewing pagination, auth, or error handling
- producing OpenAPI examples

## Fast path
1. Read the target endpoint or spec.
2. Load `references/error-format.md` if response errors are relevant.
3. Load `references/pagination.md` if list endpoints are involved.
4. Use `templates/openapi-template.yaml` if generating a new contract.
5. Optionally run `scripts/validate_openapi.py` after producing the spec.

## Rules
- Keep error payloads stable.
- Prefer cursor pagination over offset for large datasets.
- Explicitly define auth requirements.
- Include examples for non-trivial schemas.

## Output contract
Return:
1. summary of changes
2. final API contract
3. validation checklist
4. unresolved risks

## Additional resources
- references/error-format.md
- references/pagination.md
- templates/openapi-template.yaml
- scripts/validate_openapi.py
```

这份写法符合 open skill 的基本结构：frontmatter + markdown body，并把 supporting files 明确导航出来。

---

## 8.2 如果你想兼容 Claude Code 扩展

你可以加上这些字段：

```md
---
name: deploy-service
description: Deploys a service to production. Use only when the user explicitly requests deployment.
disable-model-invocation: true
user-invocable: true
argument-hint: [service-name] [environment]
allowed-tools: Bash(kubectl *) Bash(helm *) Read
context: fork
agent: general-purpose
---

Deploy service $0 to environment $1.

Steps:
1. Confirm target environment.
2. Check deployment preconditions.
3. Run deployment.
4. Verify rollout.
5. Summarize result and rollback path.
```

这些字段是 Claude Code 的扩展，而不是 open spec 的最小必需集合。

---

# 九、哪些字段应当被 runtime “特殊处理”

这是最容易被忽略的实现细节。

## 9.1 应被用于发现/路由的字段
- `name`
- `description`
- `tags`（如果你自己加）
- `scope`
- `version`
- `disable-model-invocation`
- `user-invocable`

## 9.2 应被用于执行策略的字段
- `allowed-tools`
- `context`
- `agent`
- `model`
- `hooks`

## 9.3 应被用于渲染/替换的字段
- `$ARGUMENTS`
- `$ARGUMENTS[N]`
- `$N`
- `${CLAUDE_SESSION_ID}`
- `${CLAUDE_SKILL_DIR}`

Claude Code 还支持在 skill 内容里使用 `!command` 预处理，把 shell 命令输出先执行出来，再把结果喂给模型。

如果你自己做 runtime，我建议也做类似两类替换：

1. **纯文本占位替换**：`$ARGUMENTS`、`${SESSION_ID}`  
2. **受控命令替换**：`!command`，但必须跑在严格沙箱里，且只对白名单 skill 开放。  

这是因为官方已经证明这种模式很好用，但它也天然带来安全风险。

---

# 十、严格可移植 vs 本地宽松：你要选哪一档

这里有个很重要的现实问题：

- **open spec / API 上传**：倾向于更严格，强调 `name` / `description`、字符约束、无 XML、无保留词。
- **Claude Code 本地 skill**：更宽松，`name` 可从目录名推导，`description` 甚至可从正文首段推导；也就是“能跑就先跑”。

所以我的建议是：

- **如果你要做自己平台的长期规范**：采用**严格 portable 模式**；
- **如果只是本地实验**：可以允许 runtime 自动补缺。  

也就是说，**规范层要严，开发体验层可以宽松**。

---

# 十一、你自己的 Agent Runtime，建议如何定义“skill 调用文档”

如果你是要给团队写一份内部规范文档，我建议把文档分成下面 8 章。

## 11.1 Skill 根目录规范
定义：
- 全局目录：`~/.agent/skills/`
- 项目目录：`<repo>/.agent/skills/`
- 优先级：建议项目 > 全局 > 内置  
这部分是我对你系统的推荐，不是 open spec 强制。Claude Code 自己的优先级与位置定义略有不同。

## 11.2 Skill 目录结构规范
要求：
- 必须有 `SKILL.md`
- 可选 `references/`、`templates/`、`scripts/`、`assets/`

## 11.3 Frontmatter Schema
至少包括：
- `name`
- `description`
- `version`
- `owner`
- `allowed_tools`
- `invocation_mode`
- `execution_mode`

其中后 4 个是**你可自定义的运行时字段**，相当于把 open spec 和你自己的 agent policy 融合起来。

## 11.4 Skill Discovery 规范
定义 runtime 如何：
- 扫描
- 去重
- 冲突解决
- 缓存
- 热更新

## 11.5 Skill Activation 规范
定义：
- 自动触发规则
- 手动触发语法
- 参数传递
- 多 skill 组合策略

## 11.6 Skill Execution 规范
定义：
- inline 执行
- fork/subagent 执行
- tool 权限继承或覆盖
- 脚本执行沙箱

## 11.7 Skill Security 规范
定义：
- 信任来源
- 签名/哈希
- 白名单命令
- 禁止网络 / 限制网络
- 禁止危险路径访问

## 11.8 Skill Evaluation 规范
官方最佳实践很强调：先做评估，再迭代 skill。也建议用一个 Claude 实例帮助编写 skill，另一个实例做真实任务测试。

---

# 十二、最容易踩的坑

## 12.1 把所有知识都塞进 `SKILL.md`
这是最常见错误。官方建议明确是：正文保持精炼，长材料拆进独立文件，500 行以内最佳。

## 12.2 description 写得像 marketing slogan
比如：

```yaml
description: A powerful tool for data tasks
```

这种几乎等于没写。description 应该同时写清：
- 做什么
- 什么时候用
- 触发词/文件类型/场景

## 12.3 把脚本源码当参考文档喂给模型
脚本更适合作为“执行资源”，不是“全文上下文材料”。Claude 文档里也把 helper script 定义为 executed, not loaded。

## 12.4 不区分 knowledge skill 和 action skill
如果一个 skill 会产生副作用，比如 deploy、commit、发消息，建议默认：
- 禁止模型自动触发；
- 只允许用户显式触发；
- 或强制在隔离 subagent / 强权限审批链里运行。Claude Code 就提供了 `disable-model-invocation`、`context: fork`、`allowed-tools` 等机制来做这件事。

## 12.5 在 API/SDK/CLI 三个面上混用同一语义，没做适配
这点很重要：  
Claude API、Claude Code、Agent SDK 虽然共享同一 skill 思想，但传递方式并不完全一样：

- API：`/v1/skills` + `container.skills`
- SDK：文件系统 + `setting_sources` + `allowed_tools=["Skill"]`
- Claude Code：文件系统本地发现 + `/skill-name` + frontmatter 扩展。

---

# 十三、我给你的最终落地建议

如果你的目标是“做一套自己的 agent skills 调用文档与实现”，我建议采用下面这个策略：

## 方案：双层规范

### 层 1：**Portable Skill Spec**
面向未来兼容与跨 agent 迁移，只保留：

- `name`
- `description`
- `license`
- `compatibility`
- `metadata`
- Markdown body
- `references/` / `templates/` / `scripts/`

这层尽量贴近 open SKILL.md 规范。

### 层 2：**Runtime Extension Spec**
为你自己的 agent 增加：

- `invocation-mode: auto | manual | hidden`
- `execution-mode: inline | fork`
- `tool-policy`
- `agent-profile`
- `hooks`
- `substitutions`
- `approval-policy`

这层相当于借鉴 Claude Code 的扩展能力，但以你自己的 runtime 命名来定义。Claude Code 当前确实已经证明这些扩展很有价值。

---

# 十四、一句话总结

如果只用一句话概括：

> **SKILL.md 的本质不是“提示词文件”，而是“Agent 的可发现能力包入口”。它的 frontmatter 负责让模型知道“什么时候该用我”，正文负责告诉模型“具体怎么做”，同目录资源负责提供“执行时才读取的细节与脚本”。而一个成熟的 agent runtime，应该只在启动时暴露 skill 元数据，在被选中时再按需把正文、参考资料和脚本逐级加载给模型或子代理。** 

如果你愿意，我下一步可以继续给你两份内容之一：

1. **一份完整的《Skill 规范 RFC》Markdown 文档模板**，适合你直接发给团队；  
2. **一份参考实现**：用 Python/TypeScript 实现 `~/.agent/skills` 的扫描、索引、触发、加载与执行。

---

# Agent Skills 深度分析报告：SKILL.md 格式、目录结构与 LLM 调用机制

---

## 一、概述：什么是 Agent Skills？

Agent Skills 是一种轻量级、开放的格式，用于扩展 AI agent 的专业知识与工作流。 SKILL.md 是一个开放标准，用于将可复用的能力打包，使 AI 编码 agent 可以按需发现并激活。该格式由 Anthropic 创建，在 agentskills.io 上标准化，目前已被 27+ AI agent 支持，包括 Claude Code、Cursor、Codex、Gemini CLI 和 VS Code。

核心定位：MCP 给你的 agent 提供对外部工具和数据的访问权限；而 Skills 教会你的 agent 如何使用这些工具和数据。

---

## 二、目录结构规范

### 2.1 标准目录布局

标准的 Skill 目录结构如下：

```
my-skill/
├── SKILL.md          # 必须：指令 + 元数据
├── scripts/          # 可选：可执行代码 (Python, Bash, JS)
├── references/       # 可选：额外文档
└── assets/           # 可选：模板、资源文件
```

一个 Skill 的核心就是一个包含 SKILL.md 文件的文件夹。

### 2.2 文件存放位置（多级作用域）

不同 Agent 有不同的 Skill 存放路径：

| 作用域 | Claude Code 路径 | Codex 路径 | VS Code / Copilot 路径 |
|--------|------------------|------------|----------------------|
| **个人级** | `~/.claude/skills/{skill}/SKILL.md` | `~/.codex/skills/{skill}/SKILL.md` | 自定义 `chat.agentSkillsLocations` |
| **项目级** | `.claude/skills/{skill}/SKILL.md` | `.agents/skills/{skill}/SKILL.md` | `.github/skills/{skill}/SKILL.md` |
| **仓库级** | 同上（向上扫描到 repo 根） | Codex 会扫描从当前目录到仓库根的每个目录中的 `.agents/skills` | 同上 |

VS Code 中，SKILL.md frontmatter 中的 name 字段必须与父目录名称匹配。例如，如果目录是 `skills/my-skill/`，则 name 字段必须是 `my-skill`。如果名称不匹配，skill 将不会被加载。

### 2.3 辅助目录的用途

| 目录 | 用途 | 加载时机 |
|------|------|----------|
| `scripts/` | 包含 agent 可以运行的可执行代码。脚本应该是自包含的或清晰记录依赖项。 | Agent 需要时执行 |
| `references/` | 包含 agent 可以按需读取的额外文档：领域特定文件（如 finance.md、legal.md 等）。保持单个 reference 文件聚焦。Agent 按需加载它们，因此更小的文件意味着更少的上下文占用。 | 按需加载 |
| `assets/` | 模板文件、图片、logo、数据文件等 | 按需引用 |

---

## 三、SKILL.md 文件格式详解

### 3.1 整体结构

frontmatter 配置 skill 如何运行（权限、模型、元数据），而 markdown 内容告诉 Claude 做什么。Frontmatter 是 markdown 文件头部用 YAML 编写的部分。

```markdown
---
name: my-skill-name
description: >-
  简短但精确地说明这个 skill 做什么，
  以及何时应该使用它。
license: Apache-2.0
metadata:
  author: your-org
  version: "1.0"
---

# Skill 标题

这里是详细的指令内容...
```

### 3.2 YAML Frontmatter 字段说明

Frontmatter 必须从文件第 1 行以 `---` 开始，并以另一个 `---` 结束。

#### 必需字段

| 字段 | 说明 | 约束 |
|------|------|------|
| `name` | 最多 64 个字符，小写字母、数字、连字符 | 必须与文件夹名匹配（kebab-case） |
| `description` | 最多 1024 个字符，说明 skill 做什么以及何时使用 | **这是 Agent 路由决策的关键** |

#### 可选字段

| 字段 | 说明 |
|------|------|
| `license` | 许可证标识（如 `Apache-2.0`、`MIT`） |
| `metadata` | 任意键值对（author, version 等） |
| `compatibility` | 环境需求（如所需的系统包、网络访问需求等） |
| `allowed-tools` | 安全约束，限制 skill 可用的工具列表 |

#### Claude Code 扩展字段

Claude Code 在开放标准基础上增加了更多强大的 frontmatter 字段：

| 字段 | 说明 |
|------|------|
| `context` | 设为 `fork` 则在子 agent 中运行，隔离上下文窗口 |
| `agent` | 指定子 agent 类型（如 `Explore`、`Plan`） |
| `allowed-tools` | 如 `Bash(gh *)` 限制仅允许特定 shell 命令 |
| `user-invocable` | 是否出现在 `/` 斜杠命令菜单中 |
| `disable-model-invocation` | 禁止模型自动调用，仅手动触发 |

### 3.3 Markdown Body 内容

frontmatter 之后的 Markdown body 包含 skill 指令。格式没有限制。写出能帮助 agent 有效完成任务的一切内容即可。

**推荐包含的章节：**

```markdown
# Skill 名称

## 目的
简述这个 skill 要解决什么问题

## 何时使用
- 用户要求 X 的时候
- 检测到 Y 模式的时候

## 输入要求
- 必须提供的参数/文件

## 步骤指令
1. 第一步：做什么
2. 第二步：做什么
3. ...

## 示例

### 输入示例
...

### 输出示例
...

## 边界情况
- 如果遇到 A，则...
- 如果缺少 B，则...

## 引用外部资源（按需加载）
当用户提到预算分配时，读取：`references/budget_rules.md`
```

### 3.4 动态上下文注入（Claude Code 特有）

使用 `!command` 语法可以在 skill 内容发送给 Claude 之前运行 shell 命令。命令输出会替换占位符，因此 Claude 接收到的是实际数据，而不是命令本身。

```markdown
---
name: pr-summary
description: Summarize changes in a pull request
context: fork
agent: Explore
allowed-tools: Bash(gh *)
---

## Pull request context
- PR diff: !`gh pr diff`
- PR comments: !`gh pr view --comments`
- Changed files: !`gh pr diff --name-only`

## Your task
Summarize this pull request...
```

gh 命令先执行，输出被插入到提示词中。这是预处理，不是 Claude 执行的。Claude 只看到最终结果。

### 3.5 关键写作原则

保持 SKILL.md 在 500 行以下，将详细参考材料移到独立文件中。

保持 SKILL.md 简洁（5000 词以下）可以避免超出 Claude 的上下文窗口。捆绑资源让你在不膨胀主提示词的情况下提供详细文档、自动化脚本和模板。

**description 是成败关键：**

如果你的 skill 没有触发，问题几乎从来不是 instructions，而是 description。这是大多数人在经过一个小时的沮丧之后才搞清楚的事情。

好 description 写法示例：

```yaml
# ❌ 模糊的 description
description: Helps with code

# ✅ 精确的 description（包含触发短语）
description: >-
  Reviews Python/JavaScript code for security vulnerabilities,
  PEP 8 compliance, and performance issues. Use when user asks
  to "review code", "check for bugs", "security audit", or
  "code quality check".
```

---

## 四、三阶段渐进式披露架构（Progressive Disclosure）

这是整个 Skills 系统最精妙的设计。Agent Skills 使用三阶段渐进式披露模式来最小化上下文使用：

```
┌──────────────────────────────────────────────────────────────────┐
│  阶段 1: Advertise (宣告)  ~100 tokens/skill                     │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ System Prompt 中注入:                                     │    │
│  │  "pdf-processing - Extract text from PDF files..."       │    │
│  │  "git-commit-writer - Generates commit messages..."      │    │
│  │  "webapp-testing - Guide for testing with Playwright..." │    │
│  └──────────────────────────────────────────────────────────┘    │
│       ↓ 用户请求匹配某个 skill 的 description                    │
├──────────────────────────────────────────────────────────────────┤
│  阶段 2: Load (加载)  < 5000 tokens 建议                         │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Agent 调用 load_skill 工具                                │    │
│  │ → 读取完整的 SKILL.md body                                │    │
│  │ → 指令注入到对话上下文中                                   │    │
│  └──────────────────────────────────────────────────────────┘    │
│       ↓ 指令中引用了外部资源                                     │
├──────────────────────────────────────────────────────────────────┤
│  阶段 3: Read Resources (读取资源)  按需                         │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Agent 调用 read_skill_resource 工具                       │    │
│  │ → 读取 references/budget_rules.md                        │    │
│  │ → 执行 scripts/setup.sh                                  │    │
│  │ → 加载 assets/template.json                              │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

这个三级加载系统意味着你可以安装很多 skill 而不消耗上下文。Copilot 只加载每个任务相关的内容。

---

## 五、Skills 传递给大模型的技术机制

### 5.1 Meta-Tool 架构

skills 系统通过一个 meta-tool 架构运作，其中一个名为 "Skill" 的工具充当所有单个 skill 的容器和分发器。这种设计从实现和目的上根本性地区分了 skills 和传统 tools。

传统工具如 Read、Bash 或 Write 执行离散动作并返回即时结果。Skills 的运作方式不同。它们不直接执行动作，而是将专门的指令注入到对话历史中，动态修改 Claude 的执行环境。

### 5.2 完整生命周期

```
用户发送请求
    │
    ▼
┌─────────────────────────────────┐
│  LLM 接收到:                     │
│  1. 用户消息                     │
│  2. 可用工具 (Read, Write, Bash) │
│  3. Skill 元工具                 │
│     ├── skill-a: "desc..."      │
│     ├── skill-b: "desc..."      │
│     └── skill-c: "desc..."      │
└─────────────────────────────────┘
    │
    ▼  LLM 纯推理决策（无关键词匹配、无分类器）
┌─────────────────────────────────┐
│  LLM 决定调用 skill-b           │
│  → tool_call: Skill(skill-b)   │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  运行时加载 SKILL.md body       │
│  → 指令作为新的 user message    │
│    注入对话上下文               │
│  → 修改执行上下文:              │
│    - 调整 allowed-tools         │
│    - 可能切换模型               │
│    - 调整 thinking tokens       │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  LLM 在增强环境下继续执行       │
│  → 按 skill 指令操作            │
│  → 按需读取 references/         │
│  → 按需执行 scripts/            │
└─────────────────────────────────┘
```

skill 选择机制在代码层面没有算法路由或意图分类。系统不使用 embedding、分类器或模式匹配来决定调用哪个 skill。相反，系统将所有可用 skill 格式化为嵌入在 Skill 工具提示中的文本描述，让 Claude 的语言模型做出决策。这是纯 LLM 推理。没有正则、没有关键词匹配、没有基于 ML 的意图检测。决策发生在 Claude 的 transformer 前向传播中，而非应用代码中。

### 5.3 如何集成到自建 Agent 中

在发现阶段，你只提取 YAML frontmatter（name, description）。完整的 markdown 内容保留在磁盘上直到需要时。然后将每个 skill 转换为 OpenAI function tool。LLM 将这些视为可调用函数。

**实现伪代码（Python 参考）：**

```python
import os, yaml, glob

class SkillsManager:
    def __init__(self, skills_dirs: list[str]):
        self.skills = {}
        for d in skills_dirs:
            self._scan_directory(d)

    def _scan_directory(self, base_dir: str):
        """阶段1: 发现 — 仅读取 frontmatter"""
        for skill_md in glob.glob(f"{base_dir}/*/SKILL.md"):
            raw = open(skill_md).read()
            # 解析 YAML frontmatter
            if raw.startswith("---"):
                _, fm_str, body = raw.split("---", 2)
                fm = yaml.safe_load(fm_str)
                self.skills[fm["name"]] = {
                    "name": fm["name"],
                    "description": fm["description"],
                    "path": os.path.dirname(skill_md),
                    "body": body.strip(),  # 延迟使用
                    "metadata": fm.get("metadata", {}),
                }

    def get_tool_definitions(self) -> list[dict]:
        """生成 tool definitions 注入到 LLM 请求中"""
        tools = []
        for name, skill in self.skills.items():
            tools.append({
                "type": "function",
                "function": {
                    "name": f"activate_skill_{name}",
                    "description": skill["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "const": name
                            }
                        },
                        "required": ["skill_name"]
                    }
                }
            })
        return tools

    def load_skill(self, name: str) -> str:
        """阶段2: 加载 — 返回完整指令"""
        skill = self.skills[name]
        return skill["body"]

    def read_resource(self, name: str, resource_path: str) -> str:
        """阶段3: 读取资源 — 按需加载"""
        skill = self.skills[name]
        full_path = os.path.join(skill["path"], resource_path)
        return open(full_path).read()
```

**调用流程：**

```python
# 1. 初始化
manager = SkillsManager([
    os.path.expanduser("~/.agent/skills"),  # 个人 skills
    "./.agent/skills",                       # 项目 skills
])

# 2. 构建 system prompt（注入 skill 摘要）
system_prompt = "You are a helpful agent. Available skills:\n"
for name, s in manager.skills.items():
    system_prompt += f"- {name}: {s['description']}\n"

# 3. 将 skill tools 添加到 API 请求
tools = manager.get_tool_definitions()

# 4. 发送到 LLM
response = llm_client.chat(
    system=system_prompt,
    messages=messages,
    tools=tools,
)

# 5. 处理 tool_call
if response.tool_calls:
    for call in response.tool_calls:
        if call.name.startswith("activate_skill_"):
            skill_name = call.arguments["skill_name"]
            instructions = manager.load_skill(skill_name)
            # 注入为新的 user message
            messages.append({
                "role": "user",
                "content": f"[Skill Loaded: {skill_name}]\n{instructions}"
            })
            # 继续对话
```

### 5.4 替代方案：Spring AI 的 Tool-Based 方式

在初始化期间，SkillsTool 扫描配置的 skills 目录，解析每个 SKILL.md 文件的 YAML frontmatter，提取 name 和 description 字段构建轻量级 skill 注册表，直接嵌入到 Skill 工具描述中，使其对 LLM 可见而不消耗对话上下文。

---

## 六、Skill 调用方式

### 6.1 显式调用（Explicit Invocation）

显式调用：在 prompt 中直接包含 skill。在 CLI/IDE 中，运行 `/skills` 或输入 `$` 来引用 skill。

```
/webapp-testing help me test the login page
```

### 6.2 隐式调用（Implicit / Auto-Invocation）

隐式调用：当你的任务与 skill description 匹配时，Codex 可以自动选择 skill。因为隐式匹配取决于 description，所以要写出有清晰范围和边界的 description。

```
用户: "help me write a conventional commit message"
→ Agent 自动匹配 git-commit-writer skill
```

---

## 七、完整示例：从零构建一个 Skill

### 7.1 目录

```
.agent/skills/code-review/
├── SKILL.md
├── scripts/
│   └── lint_check.py
├── references/
│   ├── style-guide.md
│   └── security-checklist.md
└── assets/
    └── review-template.md
```

### 7.2 SKILL.md

```markdown
---
name: code-review
description: >-
  Reviews code for bugs, security vulnerabilities, and best practices.
  Use when the user asks to "review code", "check for bugs",
  "security audit", "code quality", or "PR review".
license: MIT
metadata:
  author: my-team
  version: "2.0"
---

# Code Review Skill

## Purpose
Perform comprehensive code reviews focusing on security,
correctness, performance, and maintainability.

## When to Use
- User asks for code review or PR review
- User wants a security audit of their code
- User asks about code quality or best practices

## Review Process

### Step 1: Overview
Read all changed files and understand the overall intent.

### Step 2: Security Check
Review against the security checklist.
For the full checklist, read: `references/security-checklist.md`

### Step 3: Style Compliance
Run the lint check script:
```bash
python scripts/lint_check.py <file_path>
```

### Step 4: Generate Report
Use the template at `assets/review-template.md` to format findings.

## Output Format
- **Critical**: Must fix before merge
- **Warning**: Should fix, but not blocking
- **Suggestion**: Nice to have improvements

## Edge Cases
- If reviewing a generated file, skip style checks
- If the file is a config file, focus only on security
```

---

## 八、安全考量

### 8.1 供应链攻击风险

Snyk 的研究发现：13.4% 的所有 skills（共 534 个）至少包含一个关键级别的安全问题，包括恶意软件分发、提示注入攻击和暴露的 secrets。

提示注入和恶意载荷在 Agent Skills 中交汇。数据揭示了 agent 攻击的关键演变：100% 已确认的恶意 skill 包含恶意代码模式，同时 91% 同时使用了提示注入技术。

### 8.2 安全最佳实践

Agent Skills 应该像你引入项目的任何第三方代码一样对待。因为 skill 指令被注入到 agent 的上下文中 — 而且 skill 可以包含脚本 — 需要应用与开源依赖同等级别的审查和治理。使用前审查 — 在部署前阅读所有 skill 内容（SKILL.md、scripts 和 resources）。验证脚本的实际行为是否与其声明的意图匹配。检查试图绕过安全指南、窃取数据或修改 agent 配置文件的对抗性指令。

信任来源 — 只从可信作者或经过审核的内部贡献者安装 skills。优先选择有明确来源、版本控制和积极维护的 skills。注意仿冒流行包名的 typosquatted skill 名称。沙箱化 — 在隔离环境中运行包含可执行脚本的 skills。

---

## 九、Skills vs Workflows vs MCP 对比

| 维度 | Agent Skills | Workflows | MCP |
|------|-------------|-----------|-----|
| **本质** | 结构化提示 + 加载机制 | 确定性执行路径 | 外部工具协议 |
| **控制方** | AI 决定如何执行指令，适合需要 agent 创造性或自适应的场景 | 开发者显式定义 | 工具服务端 |
| **韧性** | 在单个 agent turn 中运行。如果失败，整个操作必须重试 | 支持检查点恢复 | N/A |
| **适用场景** | 聚焦的单域任务 | 多步骤业务流程 | 外部 API/数据访问 |

---

## 十、关键注意事项与常见陷阱

| 问题 | 说明 |
|------|------|
| 无效 YAML 会静默阻止加载 | 务必用 YAML lint 工具验证 |
| Skills 在会话开始时快照。运行中的会话编辑 skill 需要重启才能生效 | 修改后记得重启 agent |
| 如果 skill 显式调用有效但自动调用无效 | description 需要更具体的触发短语 |
| 如果两个 skill 同名，agent 不会合并它们 | 确保名称唯一 |
| 上下文膨胀 | 指令部分建议 < 5000 tokens，长内容拆到 references |

---

## 十一、总结

Agent Skills 的设计哲学可以概括为：

> 一个 Skill 不是插件，不是连接 API 的脚本。把它想象成为新团队成员编写的入职指南。

其核心创新在于：

1. **Markdown-native**：人类可读、可审计、可版本控制
2. **渐进式披露**：按需加载，不浪费上下文窗口
3. **LLM-native 路由**：不需要分类器，LLM 自己决策
4. **跨平台可移植**：作为开放标准，skill 可在 VS Code、GitHub Copilot CLI、GitHub Copilot coding agent 等多个 agent 间工作
5. **可组合**：skill 可以引用其他文件、执行脚本、与 MCP 协同

Claude Code 的 skill 系统已经从简单的 markdown 指令演进为一个完整的可编程 agent 平台，支持子 agent 执行、动态上下文注入、生命周期钩子和正式评估。
