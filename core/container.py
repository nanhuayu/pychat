"""Application-level dependency injection container.

Centralizes creation and wiring of all services and core components,
replacing implicit singleton patterns with explicit ownership.

Usage (in main.py or MainWindow):
    container = AppContainer()
    # Access any service:
    container.storage
    container.conv_service
    container.mcp_manager
    container.client
"""
from __future__ import annotations

from typing import Optional

from services.storage_service import StorageService
from services.provider_service import ProviderService
from services.conversation_service import ConversationService
from services.command_service import CommandService
from services.context_service import ContextService
from services.skill_service import SkillService
from core.config import load_app_config
from core.llm.client import LLMClient
from core.tools.manager import McpManager
from core.commands import CommandRegistry


class AppContainer:
    """Single owner of all application-level dependencies.

    Every component is created once and wired together here.
    UI code should access components via this container rather than
    instantiating services or managers directly.
    """

    def __init__(self) -> None:
        # -- Data & persistence
        self.storage = StorageService()
        self.app_config = load_app_config()

        # -- Core components (shared single instances)
        self.mcp_manager = McpManager()
        self.client = LLMClient(
            timeout=float(getattr(self.app_config, "llm_timeout_seconds", 600.0) or 600.0),
            mcp_manager=self.mcp_manager,
        )

        # -- Service layer
        self.provider_service = ProviderService()
        self.conv_service = ConversationService(self.storage)
        self.command_service = CommandService()
        self.context_service = ContextService(self.client)
        self.skill_service = SkillService()
        self.command_registry = CommandRegistry()
