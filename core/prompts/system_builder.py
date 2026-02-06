from __future__ import annotations

import os
import platform
from typing import Any, Dict, List, Optional

from models.conversation import Conversation
from models.provider import Provider
from utils.file_context import get_file_tree

from core.config.schema import AppConfig
from core.agent.modes.manager import resolve_mode_config
from core.agent.modes.types import normalize_mode_slug


DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful and precise assistant. Follow the user's instructions carefully and ask clarifying questions when needed."
)

DEFAULT_AGENT_TOOL_GUIDELINES = (
    "## Tool Usage\n"
    "- Use the provided tools to interact with the system.\n"
    "- Always check command outputs and handle errors.\n"
    "- If a tool fails, analyze the error and try a different approach.\n"
    "- Use `manage_state` to track progress when appropriate."
)


def build_environment_section(work_dir: str) -> str:
    os_info = platform.system() + " " + platform.release()
    file_tree = get_file_tree(work_dir, max_depth=2)
    parts = [
        "## Environment",
        f"- OS: {os_info}",
        f"- WorkDir: {os.path.abspath(work_dir)}",
        "",
        "## Workspace",
        file_tree or "(empty)",
    ]
    return "\n".join(parts).strip()


def build_state_section(conversation: Conversation) -> str:
    try:
        state = conversation.get_state()
        return state.to_prompt_view() or ""
    except Exception:
        return ""


def build_system_prompt(
    *,
    conversation: Conversation,
    tools: List[Dict[str, Any]],
    provider: Provider,
    app_config: AppConfig,
    default_work_dir: str = ".",
) -> str:
    settings = conversation.settings or {}

    prompt_cfg = app_config.prompts
    mode_slug = normalize_mode_slug(str(getattr(conversation, "mode", "chat") or "chat"))

    work_dir = getattr(conversation, "work_dir", None) or default_work_dir

    try:
        mode_cfg = resolve_mode_config(mode_slug, work_dir=str(work_dir))
    except Exception:
        mode_cfg = None

    conv_custom = ((settings.get("system_prompt") or "").strip() or (settings.get("custom_instructions") or "").strip())

    parts: list[str] = []

    role_def: Optional[str] = None
    mode_custom: Optional[str] = None

    if mode_cfg is not None:
        role_def = (mode_cfg.role_definition or "").strip() or None
        mode_custom = (mode_cfg.custom_instructions or "").strip() or None

    # System prompt precedence:
    # 1) mode.roleDefinition
    # 2) app.prompts.default_system_prompt
    # 3) app.prompts.base_role_definition (legacy)
    # 4) built-in
    if role_def:
        parts.append(role_def)
    elif (prompt_cfg.default_system_prompt or "").strip():
        parts.append(prompt_cfg.default_system_prompt.strip())
    elif (prompt_cfg.base_role_definition or "").strip():
        parts.append(prompt_cfg.base_role_definition.strip())
    else:
        parts.append(DEFAULT_SYSTEM_PROMPT)

    if (prompt_cfg.agent_tool_guidelines or "").strip():
        parts.append(prompt_cfg.agent_tool_guidelines.strip())
    else:
        parts.append(DEFAULT_AGENT_TOOL_GUIDELINES)

    if bool(prompt_cfg.include_environment):
        parts.append(build_environment_section(str(work_dir)))

    if bool(prompt_cfg.include_state):
        state_section = build_state_section(conversation)
        if state_section:
            parts.append(state_section)

    combined_custom = "\n\n".join(
        [x for x in [mode_custom, conv_custom] if isinstance(x, str) and x.strip()]
    ).strip()
    if combined_custom:
        parts.append(f"## Custom Instructions\n{combined_custom}")

    return "\n\n".join([p for p in parts if isinstance(p, str) and p.strip()]).strip()
