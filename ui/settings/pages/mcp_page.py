from __future__ import annotations

from services.storage_service import StorageService
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.dialogs.mcp_server_dialog import McpSettingsWidget


class McpPage(QWidget):
    page_emoji = "🔌"
    page_title = "MCP 服务器"

    def __init__(self, storage_service: StorageService | None = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("MCP 服务器配置"))
        layout.addWidget(McpSettingsWidget(storage_service=storage_service))
        hint = QLabel(
            "提示：启用 MCP 后，应用会自动提供内置工具（builtin_filesystem_ls/read/grep、builtin_python_exec），\n"
            "无需额外安装服务器；也可在上方添加外部 MCP Server 以扩展更多工具。"
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
