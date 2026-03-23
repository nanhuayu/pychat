"""Composer toolbar extracted from input_area.py."""
from __future__ import annotations

import logging
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QSizePolicy, QToolButton, QWidget,
)
from PyQt6.QtCore import pyqtSignal


logger = logging.getLogger(__name__)


class ComposerToolbar(QWidget):
    """Toolbar widget for provider/model/mode controls."""

    attach_requested = pyqtSignal()
    conversation_settings_requested = pyqtSignal()
    provider_settings_requested = pyqtSignal()
    prompt_optimize_requested = pyqtSignal()
    prompt_optimize_cancel_requested = pyqtSignal()
    send_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prompt_optimize_busy = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.attach_btn = self._make_button("📎", "添加文件/图片")
        self.attach_btn.clicked.connect(self.attach_requested.emit)
        layout.addWidget(self.attach_btn)

        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("provider_combo")
        self.provider_combo.setMinimumWidth(70)
        self.provider_combo.setMaximumWidth(110)
        layout.addWidget(self.provider_combo)

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("model_combo")
        self.model_combo.setMinimumWidth(120)
        self.model_combo.setMaximumWidth(200)
        self.model_combo.setEditable(True)
        layout.addWidget(self.model_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("mode_combo")
        self.mode_combo.setMinimumWidth(70)
        self.mode_combo.setToolTip("选择对话模式")
        layout.addWidget(self.mode_combo)

        self.thinking_toggle = self._make_toggle("🧠", "显示思考过程")
        layout.addWidget(self.thinking_toggle)

        self.mcp_toggle = self._make_toggle("🔌", "启用 MCP 工具")
        layout.addWidget(self.mcp_toggle)

        self.search_toggle = self._make_toggle("🔍", "启用网络搜索")
        layout.addWidget(self.search_toggle)

        self.conv_settings_btn = self._make_button("⚙", "对话设置 (采样参数/系统提示)")
        self.conv_settings_btn.clicked.connect(self.conversation_settings_requested.emit)
        layout.addWidget(self.conv_settings_btn)

        self.provider_settings_btn = self._make_button("🔧", "配置服务商 (API/Key/模型列表)")
        self.provider_settings_btn.clicked.connect(self.provider_settings_requested.emit)
        layout.addWidget(self.provider_settings_btn)

        layout.addStretch()

        self.prompt_optimize_btn = self._make_button("✨", "优化提示词")
        self.prompt_optimize_btn.clicked.connect(self._handle_prompt_optimize_clicked)
        layout.addWidget(self.prompt_optimize_btn)

        self.send_btn = self._make_button("", "发送消息 (Ctrl+Enter)")
        self._set_send_button_icon(is_streaming=False, style=self.style())
        self.send_btn.clicked.connect(self.send_requested.emit)
        layout.addWidget(self.send_btn)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _make_button(self, text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("toolbar_btn")
        button.setText(text)
        button.setToolTip(tooltip)
        return button

    def _make_toggle(self, text: str, tooltip: str) -> QToolButton:
        button = self._make_button(text, tooltip)
        button.setCheckable(True)
        return button

    def set_streaming_state(self, is_streaming: bool, style) -> None:
        self._set_send_button_icon(is_streaming=is_streaming, style=style)
        if is_streaming:
            self.prompt_optimize_btn.setEnabled(False)
            self.mcp_toggle.setEnabled(False)
            self.search_toggle.setEnabled(False)
            return

        self.prompt_optimize_btn.setEnabled(True)

    def _set_send_button_icon(self, *, is_streaming: bool, style) -> None:
        try:
            pixmap = style.StandardPixmap.SP_MediaStop if is_streaming else style.StandardPixmap.SP_ArrowRight
            self.send_btn.setIcon(style.standardIcon(pixmap))
        except Exception as exc:
            logger.debug("Failed to set send button icon on composer toolbar: %s", exc)
        self.send_btn.setText("")
        self.send_btn.setToolTip("停止生成" if is_streaming else "发送消息 (Ctrl+Enter)")

    def set_prompt_optimize_busy(self, busy: bool, *, is_streaming: bool) -> None:
        self._prompt_optimize_busy = bool(busy)
        self.prompt_optimize_btn.setEnabled(not is_streaming)
        self.prompt_optimize_btn.setText("■" if busy else "✨")
        self.prompt_optimize_btn.setToolTip("取消提示词优化" if busy else "优化提示词")

    def _handle_prompt_optimize_clicked(self) -> None:
        if self._prompt_optimize_busy:
            self.prompt_optimize_cancel_requested.emit()
            return
        self.prompt_optimize_requested.emit()
