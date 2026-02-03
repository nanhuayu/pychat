from __future__ import annotations

from core.modes.types import GroupOptions, ModeConfig


DEFAULT_MODES: list[ModeConfig] = [
    ModeConfig(
        slug="chat",
        name="Chat",
        role_definition=(
            "You are a helpful and precise assistant. Follow the user's instructions carefully."
        ),
        when_to_use="日常对话、问答、写作、解释代码。",
        description="通用聊天助手（无工具/工作区约束）",
        groups=("read",),
        source="builtin",
    ),
    ModeConfig(
        slug="agent",
        name="Agent",
        role_definition=(
            "You are a highly skilled software engineer working in a local environment with access to tools."
        ),
        when_to_use="需要读/改代码、运行命令、检索项目上下文。",
        description="工具型执行助手",
        groups=("read", "edit", "command", "mcp", "search"),
        source="builtin",
    ),
    ModeConfig(
        slug="architect",
        name="Architect",
        role_definition=(
            "You are an experienced technical leader who is inquisitive and an excellent planner. "
            "Your goal is to gather context and propose a detailed plan before implementation."
        ),
        when_to_use="需要先设计/拆解/做技术方案与里程碑。",
        description="先规划再实现",
        groups=("read", "mcp", "search"),
        custom_instructions=(
            "先做信息收集，提出清晰可执行的 todo 列表；必要时提出澄清问题。"
        ),
        source="builtin",
    ),
    ModeConfig(
        slug="code",
        name="Code",
        role_definition=(
            "You are a highly skilled software engineer. Implement the requested changes with precision."
        ),
        when_to_use="需要写代码、重构、加功能、修 bug。",
        description="专注实现",
        groups=("read", "edit", "command", "mcp"),
        source="builtin",
    ),
    ModeConfig(
        slug="ask",
        name="Ask",
        role_definition=(
            "You are a knowledgeable technical assistant focused on answering questions and explaining concepts."
        ),
        when_to_use="需要解释概念、分析代码、给出建议但不直接改代码。",
        description="解释与建议",
        groups=("read", "mcp", "search"),
        source="builtin",
    ),
    ModeConfig(
        slug="debug",
        name="Debug",
        role_definition=(
            "You are an expert software debugger specializing in systematic diagnosis and resolution."
        ),
        when_to_use="排查崩溃/异常/行为不符合预期，添加日志与最小修复。",
        description="系统化调试",
        groups=("read", "edit", "command", "mcp", "search"),
        custom_instructions=(
            "先列出可能原因并收敛到最可能的 1-2 个，再用日志/实验验证后修复。"
        ),
        source="builtin",
    ),
    ModeConfig(
        slug="orchestrator",
        name="Orchestrator",
        role_definition=(
            "You are a strategic workflow orchestrator who coordinates complex tasks by delegating them into sub-tasks."
        ),
        when_to_use="大型多步骤项目，需要拆解并按模块推进。",
        description="流程编排",
        groups=(),
        custom_instructions=(
            "先拆分为多个可并行/可验证的子任务，并明确每个子任务的输入/输出与边界。"
        ),
        source="builtin",
    ),
]


def get_default_modes() -> list[ModeConfig]:
    return list(DEFAULT_MODES)
