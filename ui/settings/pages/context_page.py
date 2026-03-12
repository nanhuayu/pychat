from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from core.config.schema import ContextConfig, CompressionPolicyConfig
from ui.utils.form_builder import FormSection


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

        ctx = FormSection("上下文窗口")
        self.default_max_context_messages = ctx.add_spin(
            "默认上下文消息数", value=int(context.default_max_context_messages or 0),
            range=(0, 200), tooltip="默认值；0 表示不限制（由模型/服务商上下文上限决定）",
        )
        layout.addWidget(ctx.group)

        pol = context.compression_policy
        agent = FormSection("自动压缩")
        self.agent_auto_compress_enabled = agent.add_checkbox(
            "启用自动压缩", checked=bool(context.agent_auto_compress_enabled),
        )
        self.comp_max_active_messages = agent.add_spin(
            "活跃消息上限", value=int(pol.max_active_messages or 20), range=(5, 200),
        )
        self.comp_token_threshold_ratio = agent.add_double_spin(
            "Token 阈值比例", value=float(pol.token_threshold_ratio or 0.70),
            range=(0.10, 0.95), step=0.05,
        )
        self.comp_keep_last_n = agent.add_spin(
            "保留最后 N 条", value=int(pol.keep_last_n or 10), range=(2, 50),
        )
        layout.addWidget(agent.group)
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
