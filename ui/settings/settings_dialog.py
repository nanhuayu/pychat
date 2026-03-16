"""Settings dialog (thin container).

This dialog hosts modular setting pages under `ui.settings.pages`.

Notes:
- Modes are user-wide (APPDATA/PyChat/modes.json), edited via `ModesPage`.
- Prompt templates (default/system guidelines, optimizer templates) remain user-wide in settings.json.
"""

from __future__ import annotations

import logging
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QPushButton,
    QFrame,
    QSizePolicy,
    QMessageBox,
)

from models.provider import Provider
from services.provider_service import ProviderService
from services.storage_service import StorageService
from core.config.schema import AppConfig

from ui.settings.pages import (
    ModelsPage,
    ModesPage,
    ContextPage,
    PromptsPage,
    AgentPermissionsPage,
    McpPage,
    SearchPage,
    AppearancePage,
    GeneralPage,
    SkillsPage,
)


logger = logging.getLogger(__name__)


def create_emoji_icon(emoji: str, size: int = 20) -> QIcon:
    """Render emoji as icon, keeping alignment consistent on Windows."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    font = QFont("Segoe UI Emoji", max(6, size - 8))
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignLeft, emoji)
    painter.end()
    return QIcon(pixmap)


class SettingsDialog(QDialog):
    """Thin container dialog."""

    providers_changed = pyqtSignal()

    def __init__(
        self,
        providers: List[Provider],
        current_settings: dict | None = None,
        provider_service: ProviderService | None = None,
        storage_service: StorageService | None = None,
        parent=None,
        work_dir: str | None = None,
    ):
        super().__init__(parent)
        self.providers = list(providers or [])
        self.current_settings = current_settings or {}
        self.work_dir = str(work_dir or "")

        self.provider_service = provider_service or ProviderService()
        self.storage = storage_service or StorageService()
        self.search_config = self.storage.load_search_config()
        self._app_config = AppConfig.from_dict(self.current_settings)

        self._appearance_patch: dict = {}
        self._general_patch: dict = {}
        self._auto_approve_patch: dict = {}
        self._context_patch: dict = {}
        self._prompt_patch: dict = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("设置")
        self.setObjectName("settings_dialog")
        self.setModal(True)
        self.setMinimumSize(800, 560)
        try:
            self.resize(850, 600)
        except Exception as exc:
            logger.debug("Failed to resize settings dialog: %s", exc)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("settings_sidebar")
        # Wider left panel for long titles.
        sidebar.setFixedWidth(210)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(6)

        self.page_list = QListWidget()
        self.page_list.setObjectName("settings_nav")
        self.page_list.setIconSize(QSize(18, 18))
        self.page_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.page_list.currentRowChanged.connect(self._change_page)
        sidebar_layout.addWidget(self.page_list, 1)

        sidebar_layout.addSpacing(6)
        save_btn = QPushButton("保存")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self.accept)
        sidebar_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        sidebar_layout.addWidget(cancel_btn)

        layout.addWidget(sidebar)

        self.content = QStackedWidget()
        self.content.setObjectName("settings_content")
        layout.addWidget(self.content)

        self._init_pages()
        self.page_list.setCurrentRow(0)

    def _init_pages(self) -> None:
        self.page_list.clear()

        self.models_page = ModelsPage(self.providers, self.provider_service)
        # Modes are global user config; ModesPage ignores work_dir.
        self.modes_page = ModesPage(self.work_dir)
        self.context_page = ContextPage(self._app_config.context)
        self.prompts_page = PromptsPage(
            self._app_config.prompts,
            self._app_config.prompt_optimizer,
            prompt_optimizer_model=str(getattr(self._app_config, "prompt_optimizer_model", "") or ""),
        )
        self.agent_page = AgentPermissionsPage(self._app_config.permissions, retry=self._app_config.retry)
        self.mcp_page = McpPage(storage_service=self.storage)
        self.search_page = SearchPage(self.search_config)
        self.appearance_page = AppearancePage(
            theme=self._app_config.theme,
            show_stats=self._app_config.show_stats,
            show_thinking=self._app_config.show_thinking,
            log_stream=self._app_config.log_stream,
        )
        self.general_page = GeneralPage(
            proxy_url=self._app_config.proxy_url,
            llm_timeout_seconds=float(getattr(self._app_config, "llm_timeout_seconds", 600.0) or 600.0),
        )
        self.skills_page = SkillsPage(work_dir=self.work_dir)

        self._pages = [
            self.models_page,
            self.modes_page,
            self.context_page,
            self.prompts_page,
            self.agent_page,
            self.mcp_page,
            self.search_page,
            self.skills_page,
            self.appearance_page,
            self.general_page,
        ]

        for page in self._pages:
            self.content.addWidget(page)
            emoji = str(getattr(page, "page_emoji", "⚙️"))
            title = str(getattr(page, "page_title", "设置"))
            try:
                icon = create_emoji_icon(emoji, 20)
            except Exception:
                icon = QIcon()
            item = QListWidgetItem(icon, "  " + title)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.page_list.addItem(item)

        try:
            self.models_page.providers_changed.connect(self.providers_changed)
        except Exception as exc:
            logger.debug("Failed to connect providers_changed signal in settings dialog: %s", exc)

    def _change_page(self, index: int) -> None:
        self.content.setCurrentIndex(int(index))

    def accept(self) -> None:
        try:
            if not self.modes_page.save_to_disk():
                QMessageBox.warning(self, "模式配置无效", "请先修正 modes.json 后再保存。")
                return
        except Exception as exc:
            logger.debug("Failed to persist modes configuration from settings dialog: %s", exc)

        try:
            self.providers = self.models_page.get_providers()
        except Exception as exc:
            logger.debug("Failed to collect providers from settings dialog: %s", exc)

        try:
            self.search_config = self.search_page.collect()
            self.storage.save_search_config(self.search_config)
        except Exception as exc:
            logger.debug("Failed to collect or save search configuration: %s", exc)

        try:
            self._appearance_patch = dict(self.appearance_page.collect() or {})
        except Exception:
            self._appearance_patch = {}

        try:
            self._general_patch = dict(self.general_page.collect() or {})
        except Exception:
            self._general_patch = {}

        try:
            perms = self.agent_page.collect()
            self._auto_approve_patch = perms.to_dict()
        except Exception as exc:
            logger.debug("Failed to collect agent permission settings: %s", exc)
            self._auto_approve_patch = {}

        try:
            self._retry_patch = self.agent_page.collect_retry().to_dict()
        except Exception:
            self._retry_patch = {}

        try:
            ctx = self.context_page.collect()
            self._context_patch = {"context": ctx.to_dict()}
        except Exception:
            self._context_patch = {}

        try:
            prompts = self.prompts_page.collect_prompts()
            opt = self.prompts_page.collect_prompt_optimizer()
            self._prompt_patch = {
                "prompts": prompts.to_dict(),
                "prompt_optimizer": opt.to_dict(),
                "prompt_optimizer_model": self.prompts_page.collect_prompt_optimizer_model(),
            }
        except Exception:
            self._prompt_patch = {}

        super().accept()

    def get_providers(self) -> List[Provider]:
        return list(self.providers or [])

    def get_theme(self) -> str:
        return str(self._appearance_patch.get("theme") or self._app_config.theme)

    def get_show_stats(self) -> bool:
        return bool(self._appearance_patch.get("show_stats", self._app_config.show_stats))

    def get_show_thinking(self) -> bool:
        return bool(self._appearance_patch.get("show_thinking", self._app_config.show_thinking))

    def get_log_stream(self) -> bool:
        return bool(self._appearance_patch.get("log_stream", self._app_config.log_stream))

    def get_proxy_url(self) -> str:
        return str(self._general_patch.get("proxy_url", self._app_config.proxy_url) or "")

    def get_llm_timeout_seconds(self) -> float:
        try:
            return float(self._general_patch.get("llm_timeout_seconds", self._app_config.llm_timeout_seconds))
        except Exception:
            return float(getattr(self._app_config, "llm_timeout_seconds", 600.0) or 600.0)

    def get_auto_approve_settings(self) -> dict:
        return dict(self._auto_approve_patch or {})

    def get_retry_settings(self) -> dict:
        return dict(self._retry_patch if hasattr(self, '_retry_patch') else {})

    def get_context_settings(self) -> dict:
        return dict(self._context_patch or {})

    def get_prompt_settings(self) -> dict:
        return dict(self._prompt_patch or {})
