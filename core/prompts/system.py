from typing import List, Dict, Any
from models.conversation import Conversation
from models.provider import Provider
from utils.file_context import get_file_tree
from core.modes.manager import ModeManager
from core.modes.types import normalize_mode_slug
import os
import platform

class PromptManager:
    """
    Centralized manager for system prompts and context assembly.
    """
    
    def __init__(self, work_dir: str = "."):
        self.work_dir = work_dir

    def get_system_prompt(self, 
                          conversation: Conversation, 
                          tools: List[Dict[str, Any]], 
                          provider: Provider) -> str:
        """
        Generates the dynamic system prompt.
        Now includes SessionState (summary/tasks/memory) for cognitive context.
        """
        settings = conversation.settings or {}

        mode_slug = normalize_mode_slug(str(getattr(conversation, "mode", "chat") or "chat"))

        # Resolve mode config
        try:
            work_dir = getattr(conversation, "work_dir", None) or self.work_dir
            mode_manager = ModeManager(work_dir)
            mode_cfg = mode_manager.get(mode_slug)
        except Exception:
            mode_cfg = None

        # Per-conversation custom system prompt text (UI uses `system_prompt`).
        conv_custom = (
            (settings.get("system_prompt") or "").strip()
            or (settings.get("custom_instructions") or "").strip()
        )

        parts: list[str] = []

        role_def = None
        mode_custom = None
        agent_like = False

        if mode_cfg is not None:
            role_def = (mode_cfg.role_definition or "").strip() or None
            mode_custom = (mode_cfg.custom_instructions or "").strip() or None
            try:
                agent_like = bool(mode_cfg.is_agent_like())
            except Exception:
                agent_like = (mode_slug == "agent")
        else:
            agent_like = (mode_slug == "agent")

        if role_def:
            parts.append(role_def)
        else:
            parts.append(
                "You are a helpful and precise assistant. Follow the user's instructions carefully and ask clarifying questions when needed."
            )

        if agent_like:
            tool_guidelines = (
                "## Tool Usage\n"
                "- Use the provided tools to interact with the system.\n"
                "- Always check command outputs and handle errors.\n"
                "- If a tool fails, analyze the error and try a different approach.\n"
                "- Use `manage_state` to track progress when appropriate."
            )
            parts.append(tool_guidelines)
            parts.append(self._get_environment_section())

        state_section = self._get_state_section(conversation)
        if state_section:
            parts.append(state_section)

        combined_custom = "\n\n".join([x for x in [mode_custom, conv_custom] if isinstance(x, str) and x.strip()]).strip()
        if combined_custom:
            parts.append(f"## Custom Instructions\n{combined_custom}")

        return "\n\n".join([p for p in parts if isinstance(p, str) and p.strip()]).strip()

    def _get_state_section(self, conversation: Conversation) -> str:
        """
        Generate the SessionState section for system prompt injection.
        This provides the LLM with cognitive context (summary, tasks, memory).
        """
        try:
            state = conversation.get_state()
            return state.to_prompt_view()
        except Exception:
            # Graceful fallback if state loading fails
            return ""

    def _get_environment_section(self) -> str:
        os_info = platform.system() + " " + platform.release()
        file_tree = get_file_tree(self.work_dir, max_depth=2)
        parts = [
            "## Environment",
            f"- OS: {os_info}",
            f"- WorkDir: {os.path.abspath(self.work_dir)}",
            "",
            "## Workspace",
            file_tree or "(empty)",
        ]
        return "\n".join(parts).strip()
