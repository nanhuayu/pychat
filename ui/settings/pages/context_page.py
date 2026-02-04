from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QGroupBox,
    QFormLayout,
    QSpinBox,
    QCheckBox,
    QDoubleSpinBox,
)

from core.config.schema import ContextConfig, CompressionPolicyConfig


class ContextPage(QWidget):
    page_emoji = "📚"
    page_title = "上下文管理"

    def __init__(self, context: ContextConfig, parent=None):
        super().__init__(parent)
        self._initial = context
        self._setup_ui(context)

    def _setup_ui(self, context: ContextConfig) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<h2>上下文管理</h2>"))

        ctx_group = QGroupBox("上下文窗口")
        ctx_form = QFormLayout(ctx_group)
        ctx_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        ctx_form.setHorizontalSpacing(10)
        ctx_form.setVerticalSpacing(6)

        self.default_max_context_messages = QSpinBox()
        self.default_max_context_messages.setRange(0, 200)
        self.default_max_context_messages.setSingleStep(1)
        self.default_max_context_messages.setToolTip("默认值；0 表示不限制（由模型/服务商上下文上限决定）")
        self.default_max_context_messages.setValue(int(context.default_max_context_messages or 0))
        ctx_form.addRow("默认上下文消息数", self.default_max_context_messages)

        layout.addWidget(ctx_group)

        agent_group = QGroupBox("自动压缩（Agent）")
        agent_form = QFormLayout(agent_group)
        agent_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        agent_form.setHorizontalSpacing(10)
        agent_form.setVerticalSpacing(6)

        self.agent_auto_compress_enabled = QCheckBox("启用 Agent 自动压缩")
        self.agent_auto_compress_enabled.setChecked(bool(context.agent_auto_compress_enabled))
        agent_form.addRow("", self.agent_auto_compress_enabled)

        pol = context.compression_policy

        self.comp_max_active_messages = QSpinBox()
        self.comp_max_active_messages.setRange(5, 200)
        self.comp_max_active_messages.setValue(int(pol.max_active_messages or 20))
        agent_form.addRow("活跃消息上限", self.comp_max_active_messages)

        self.comp_token_threshold_ratio = QDoubleSpinBox()
        self.comp_token_threshold_ratio.setRange(0.10, 0.95)
        self.comp_token_threshold_ratio.setSingleStep(0.05)
        self.comp_token_threshold_ratio.setDecimals(2)
        self.comp_token_threshold_ratio.setValue(float(pol.token_threshold_ratio or 0.70))
        agent_form.addRow("Token 阈值比例", self.comp_token_threshold_ratio)

        self.comp_keep_last_n = QSpinBox()
        self.comp_keep_last_n.setRange(2, 50)
        self.comp_keep_last_n.setValue(int(pol.keep_last_n or 10))
        agent_form.addRow("保留最后 N 条", self.comp_keep_last_n)

        layout.addWidget(agent_group)
        layout.addStretch()

    def collect(self) -> ContextConfig:
        pol = CompressionPolicyConfig.from_dict(
            {
                "max_active_messages": int(self.comp_max_active_messages.value()),
                "token_threshold_ratio": float(self.comp_token_threshold_ratio.value()),
                "keep_last_n": int(self.comp_keep_last_n.value()),
            }
        )
        default_max = int(self.default_max_context_messages.value())
        default_max = default_max if default_max > 0 else 0
        return ContextConfig(
            default_max_context_messages=default_max,
            agent_auto_compress_enabled=bool(self.agent_auto_compress_enabled.isChecked()),
            compression_policy=pol,
        )
