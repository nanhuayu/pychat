from __future__ import annotations

import os
import platform
from typing import Any, Dict, List, Optional

from models.conversation import Conversation
from models.provider import Provider
from utils.file_context import get_file_tree

from core.config.schema import AppConfig
from core.modes.manager import resolve_mode_config
from core.modes.types import normalize_mode_slug


DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful and precise assistant. Follow the user's instructions carefully and ask clarifying questions when needed."
)

DEFAULT_AGENT_TOOL_GUIDELINES = (
    "## Tool Usage\n"
    "- Use the provided tools to interact with the system.\n"
    "- Always check command outputs and handle errors.\n"
    "- If a tool fails, analyze the error and try a different approach.\n"
    "- Use `manage_state` to track progress and `manage_document` to keep plan/memory notes current.\n"
    "- `attempt_completion` is a built-in tool for finishing work; do not treat it as a skill or document name.\n"
    "- If another mode is a better fit, use `switch_mode`; if work should continue independently, use `new_task`."
)


def build_mode_profile_section(mode_slug: str, mode_cfg: Optional[Any]) -> str:
    lines = ["<mode_profile>", f"slug: {mode_slug}"]

    if mode_cfg is not None:
        if (mode_cfg.name or "").strip():
            lines.append(f"name: {mode_cfg.name}")
        if (mode_cfg.description or "").strip():
            lines.append(f"description: {mode_cfg.description}")
        if (mode_cfg.when_to_use or "").strip():
            lines.append(f"when_to_use: {mode_cfg.when_to_use}")
        groups = sorted(mode_cfg.group_names())
        if groups:
            lines.append(f"tool_groups: {', '.join(groups)}")

    lines.append("</mode_profile>")
    return "\n".join(lines)


def build_mode_workflow_guidance(mode_slug: str) -> str:
    slug = normalize_mode_slug(mode_slug)
    guidance: dict[str, list[str]] = {
        "agent": [
            "Maintain the current todo list with `manage_state` when scope changes or steps complete.",
            "Keep a short working plan in `manage_document(name=\"plan\")` for multi-step execution.",
            "Store durable facts such as important paths, commands, or decisions in memory instead of repeating them in chat.",
            "Use `switch_mode` if the request clearly belongs to another mode, or `new_task` if a separate delegated run is better.",
            "Use `attempt_completion` only when the task is actually complete and you can summarize the result clearly.",
        ],
        "code": [
            "Before major edits, keep a concise implementation plan in `manage_document(name=\"plan\")`.",
            "Update `manage_state.tasks` as you finish concrete coding steps.",
            "Use memory for stable repo facts that matter across later turns, such as verified commands or conventions.",
            "Switch out of code mode if the task becomes primarily architecture or debugging, rather than forcing implementation prematurely.",
            "End the run with `attempt_completion`; do not use skill-loading tools as a completion signal.",
        ],
        "debug": [
            "Track active hypotheses and verification steps in `manage_document(name=\"plan\")`.",
            "Move confirmed root causes and important repro details into memory so they persist across retries and compression.",
            "Keep the todo list focused on the remaining debug actions, not on already-finished analysis.",
            "Switch to another mode once debugging is done and the remaining work is clearly implementation or planning.",
            "Call `attempt_completion` only after the root cause and fix state are explicit.",
        ],
        "architect": [
            "Create and maintain a plan document as the primary artifact for architecture work.",
            "Use the todo list to track open design questions and decision checkpoints.",
            "Persist only confirmed constraints or decisions into memory.",
            "Switch to a more appropriate mode if the task stops being architecture work, and call `attempt_completion` once the design output is ready.",
        ],
        "orchestrator": [
            "Use the plan document to track delegation strategy and aggregate results from sub-tasks.",
            "Use the todo list for the current frontier of unfinished delegated work.",
            "Use `new_task` for independent sub-work and `switch_mode` when the current conversation should continue in another mode.",
            "Call `attempt_completion` only after delegated work has been consolidated.",
        ],
    }
    items = guidance.get(slug)
    if not items:
        return ""
    return "## State Workflow\n" + "\n".join(f"- {item}" for item in items)


def build_environment_section(work_dir: str, max_depth: int = 2) -> str:
    os_info = platform.system() + " " + platform.release()
    file_tree = get_file_tree(work_dir, max_depth=max_depth)
    parts = [
        "<environment_info>",
        f"OS: {os_info}",
        f"WorkDir: {os.path.abspath(work_dir)}",
        "</environment_info>",
        "",
        "<workspace_info>",
        file_tree or "(empty)",
        "</workspace_info>",
    ]
    return "\n".join(parts).strip()


def resolve_base_system_prompt_text(
    *,
    conversation: Conversation,
    app_config: AppConfig,
    default_work_dir: str = ".",
    include_conversation_override: bool = True,
) -> str:
    settings = conversation.settings or {}
    mode_slug = normalize_mode_slug(str(getattr(conversation, "mode", "chat") or "chat"))
    work_dir = getattr(conversation, "work_dir", None) or default_work_dir

    try:
        mode_cfg = resolve_mode_config(mode_slug, work_dir=str(work_dir))
    except Exception:
        mode_cfg = None

    if include_conversation_override:
        conv_custom = ((settings.get("system_prompt") or "").strip() or (settings.get("custom_instructions") or "").strip())
        if conv_custom:
            return conv_custom

    prompt_cfg = app_config.prompts
    if mode_cfg is not None and (mode_cfg.role_definition or "").strip():
        return mode_cfg.role_definition.strip()
    if (prompt_cfg.default_system_prompt or "").strip():
        return prompt_cfg.default_system_prompt.strip()
    if (prompt_cfg.base_role_definition or "").strip():
        return prompt_cfg.base_role_definition.strip()
    return DEFAULT_SYSTEM_PROMPT


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

    parts.append(build_mode_profile_section(mode_slug, mode_cfg))

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

    # Inject available tools summary
    if tools:
        tool_lines = ["<available_tools>"]
        for t in tools:
            fn = t.get("function", {})
            tname = fn.get("name", "")
            tdesc = (fn.get("description") or "")[:100]
            if tname:
                tool_lines.append(f"- {tname}: {tdesc}")
        tool_lines.append("</available_tools>")
        parts.append("\n".join(tool_lines))

    if bool(prompt_cfg.include_state):
        state_section = build_state_section(conversation)
        if state_section:
            parts.append(state_section)

    workflow_guidance = build_mode_workflow_guidance(mode_slug)
    if workflow_guidance:
        parts.append(workflow_guidance)

    combined_custom = "\n\n".join(
        [x for x in [mode_custom, conv_custom] if isinstance(x, str) and x.strip()]
    ).strip()
    if combined_custom:
        parts.append(f"## Custom Instructions\n{combined_custom}")

    # Inject active skills
    active_skills = (settings.get("active_skills") or [])
    if active_skills:
        from core.skills import resolve_active_skills
        for skill in resolve_active_skills(
            active_skills,
            work_dir=getattr(conversation, "work_dir", ".") or ".",
        ):
            parts.append(f'<skill name="{skill.name}">\n{skill.content}\n</skill>')

    # Inject conversation summary at the end of the system prompt
    try:
        state = conversation.get_state()
        if state.summary:
            parts.append(
                "<conversation-summary>\n"
                f"{state.summary}\n"
                "</conversation-summary>"
            )
    except Exception:
        pass

    return "\n\n".join([p for p in parts if isinstance(p, str) and p.strip()]).strip()
