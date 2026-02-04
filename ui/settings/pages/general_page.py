from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLineEdit, QLabel


class GeneralPage(QWidget):
    page_emoji = "⚙️"
    page_title = "常规设置"

    def __init__(self, *, proxy_url: str = "", parent=None):
        super().__init__(parent)
        self._setup_ui(proxy_url)

    def _setup_ui(self, proxy_url: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        net_group = QGroupBox("网络")
        net_layout = QFormLayout(net_group)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setText(proxy_url or "")
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:7890")
        net_layout.addRow("代理服务器:", self.proxy_edit)
        layout.addWidget(net_group)

        about_group = QGroupBox("关于")
        about_layout = QVBoxLayout(about_group)
        about_layout.addWidget(QLabel("PyChat v0.5.0"))
        about_layout.addWidget(QLabel("基于 PyQt6 + MCP 构建"))
        layout.addWidget(about_group)

        layout.addStretch()

    def collect(self) -> dict:
        return {"proxy_url": (self.proxy_edit.text() or "").strip()}
