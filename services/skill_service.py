"""Skill activation and discovery service."""
from __future__ import annotations

from models.conversation import Conversation
from core.skills import SkillsManager


class SkillService:
    """Workspace-aware skill operations for command and UI layers."""

    def list_for_workdir(self, work_dir: str | None) -> list:
        return SkillsManager(work_dir or ".").list_skills()

    def exists(self, skill_name: str, *, work_dir: str | None) -> bool:
        return SkillsManager(work_dir or ".").get(skill_name) is not None

    def activate_for_conversation(self, conversation: Conversation, skill_name: str) -> bool:
        work_dir = getattr(conversation, "work_dir", ".") or "."
        normalized = str(skill_name or "").strip().lower()
        if not normalized:
            return False
        if not self.exists(normalized, work_dir=work_dir):
            return False

        settings = conversation.settings or {}
        active = [str(item).strip().lower() for item in (settings.get("active_skills") or []) if str(item).strip()]
        if normalized not in active:
            active.append(normalized)
        settings["active_skills"] = active
        conversation.settings = settings
        return True