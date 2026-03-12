"""Conversation settings dialog (per-conversation overrides)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QFormLayout,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QPushButton,
    QComboBox,
    QGroupBox,
)
from PyQt6.QtCore import Qt
from typing import List, Optional

from models.conversation import Conversation
from models.provider import Provider
from core.modes.manager import ModeManager


class ConversationSettingsDialog(QDialog):
    def __init__(
        self,
        conversation: Conversation,
        providers: Optional[List[Provider]] = None,
        default_show_thinking: bool = True,
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("对话设置")
        self.setModal(True)
        self.setMinimumWidth(480)

        self._conversation = conversation
        self._providers = providers or []
        self._default_show_thinking = bool(default_show_thinking)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # ===== 基本信息 =====
        basic_group = QGroupBox("基本信息")
        form = QFormLayout(basic_group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)

        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("conv_title")
        self.title_edit.setText(conversation.title or "")
        form.addRow("名称", self.title_edit)

        self.system_prompt_edit = QTextEdit()
        self.system_prompt_edit.setObjectName("conv_system_prompt")
        self.system_prompt_edit.setPlaceholderText("例如：你是一个严谨的助手...（可选）")
        self.system_prompt_edit.setAcceptRichText(False)
        self.system_prompt_edit.setMaximumHeight(80)
        self.system_prompt_edit.setText((conversation.settings or {}).get("system_prompt", "") or "")
        form.addRow("系统提示", self.system_prompt_edit)

        root.addWidget(basic_group)

        # ===== 模型设置 =====
        model_group = QGroupBox("模型设置")
        model_form = QFormLayout(model_group)
        model_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        model_form.setHorizontalSpacing(10)
        model_form.setVerticalSpacing(6)

        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("conv_provider")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        model_form.addRow("服务商", self.provider_combo)

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("conv_model")
        self.model_combo.setEditable(True)
        model_form.addRow("模型", self.model_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("conv_mode")
        try:
            mm = ModeManager(None)
            for m in mm.list_modes():
                self.mode_combo.addItem(m.name, m.slug)
        except Exception:
            # Fallback: minimal legacy modes
            self.mode_combo.addItem("Chat", "chat")
            self.mode_combo.addItem("Agent", "agent")
        # Select current
        try:
            cur_slug = str(getattr(conversation, "mode", "chat") or "chat")
            idx = self.mode_combo.findData(cur_slug)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        except Exception:
            pass
        model_form.addRow("模式", self.mode_combo)

        # Populate providers
        for p in self._providers:
            self.provider_combo.addItem(p.name, p.id)
        # Select current
        for i, p in enumerate(self._providers):
            if p.id == conversation.provider_id:
                self.provider_combo.setCurrentIndex(i)
                break
        if conversation.model:
            self.model_combo.setCurrentText(conversation.model)

        root.addWidget(model_group)

        # ===== 压缩/优化 =====
        summary_group = QGroupBox("压缩/优化")
        summary_form = QFormLayout(summary_group)
        summary_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        summary_form.setHorizontalSpacing(10)
        summary_form.setVerticalSpacing(6)

        self.summary_model_combo = QComboBox()
        self.summary_model_combo.setObjectName("conv_summary_model")
        self.summary_model_combo.setEditable(True)
        summary_model_val = (conversation.settings or {}).get("summary_model", "") or ""
        if summary_model_val:
            self.summary_model_combo.setCurrentText(str(summary_model_val))
        summary_form.addRow("压缩模型", self.summary_model_combo)

        self.summary_include_tool_details = QCheckBox("包含工具详情（更耗 token）")
        self.summary_include_tool_details.setObjectName("conv_summary_include_tool_details")
        self.summary_include_tool_details.setChecked(bool((conversation.settings or {}).get("summary_include_tool_details", False)))
        summary_form.addRow("工具信息", self.summary_include_tool_details)

        self.summary_system_prompt_edit = QTextEdit()
        self.summary_system_prompt_edit.setObjectName("conv_summary_system_prompt")
        self.summary_system_prompt_edit.setAcceptRichText(False)
        self.summary_system_prompt_edit.setMaximumHeight(70)
        self.summary_system_prompt_edit.setPlaceholderText("可选：用于压缩/总结请求的 system prompt（留空使用内置简洁模板）")
        self.summary_system_prompt_edit.setText((conversation.settings or {}).get("summary_system_prompt", "") or "")
        summary_form.addRow("压缩System", self.summary_system_prompt_edit)

        # Prompt optimizer settings (per-conversation override)
        self.prompt_optimizer_model_combo = QComboBox()
        self.prompt_optimizer_model_combo.setObjectName("conv_prompt_optimizer_model")
        self.prompt_optimizer_model_combo.setEditable(True)
        opt_model_val = (conversation.settings or {}).get("prompt_optimizer_model", "") or ""
        if opt_model_val:
            self.prompt_optimizer_model_combo.setCurrentText(str(opt_model_val))
        summary_form.addRow("优化模型", self.prompt_optimizer_model_combo)

        self.prompt_optimizer_system_prompt_edit = QTextEdit()
        self.prompt_optimizer_system_prompt_edit.setObjectName("conv_prompt_optimizer_system_prompt")
        self.prompt_optimizer_system_prompt_edit.setAcceptRichText(False)
        self.prompt_optimizer_system_prompt_edit.setMaximumHeight(70)
        self.prompt_optimizer_system_prompt_edit.setPlaceholderText("可选：用于‘优化提示词’请求的 system prompt（留空使用内置模板）")
        self.prompt_optimizer_system_prompt_edit.setText((conversation.settings or {}).get("prompt_optimizer_system_prompt", "") or "")
        summary_form.addRow("优化System", self.prompt_optimizer_system_prompt_edit)

        root.addWidget(summary_group)

        # ===== 采样参数 =====
        params_group = QGroupBox("采样参数")
        params_form = QFormLayout(params_group)
        params_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        params_form.setHorizontalSpacing(10)
        params_form.setVerticalSpacing(6)

        self.context_limit = QSpinBox()
        self.context_limit.setObjectName("conv_context_limit")
        self.context_limit.setRange(0, 200)
        self.context_limit.setSingleStep(1)
        self.context_limit.setValue(int((conversation.settings or {}).get("max_context_messages", 0) or 0))
        self.context_limit.setToolTip("0 表示不限制")
        params_form.addRow("上下文消息数", self.context_limit)

        self.temperature = QDoubleSpinBox()
        self.temperature.setObjectName("conv_temperature")
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.05)
        self.temperature.setDecimals(2)
        temp_val = (conversation.settings or {}).get("temperature")
        self.temperature.setValue(float(temp_val) if isinstance(temp_val, (int, float)) else 0.70)
        params_form.addRow("温度", self.temperature)

        self.top_p = QDoubleSpinBox()
        self.top_p.setObjectName("conv_top_p")
        self.top_p.setRange(0.0, 1.0)
        self.top_p.setSingleStep(0.05)
        self.top_p.setDecimals(2)
        top_p_val = (conversation.settings or {}).get("top_p")
        self.top_p.setValue(float(top_p_val) if isinstance(top_p_val, (int, float)) else 1.00)
        params_form.addRow("Top P", self.top_p)

        self.max_tokens = QSpinBox()
        self.max_tokens.setObjectName("conv_max_tokens")
        self.max_tokens.setRange(0, 200000)
        self.max_tokens.setSingleStep(256)
        self.max_tokens.setValue(int((conversation.settings or {}).get("max_tokens") or 0)) # 65536
        self.max_tokens.setToolTip("最大输出 Token 数")
        params_form.addRow("最大 Token", self.max_tokens)

        root.addWidget(params_group)

        # ===== 功能开关 =====
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(16)

        self.stream_enabled = QCheckBox("流式输出")
        self.stream_enabled.setObjectName("conv_stream")
        self.stream_enabled.setChecked(bool((conversation.settings or {}).get("stream", True)))
        toggle_row.addWidget(self.stream_enabled)

        self.show_thinking = QCheckBox("显示思考")
        self.show_thinking.setObjectName("conv_show_thinking")
        show_thinking_val = (conversation.settings or {}).get("show_thinking")
        if isinstance(show_thinking_val, bool):
            self.show_thinking.setChecked(show_thinking_val)
        else:
            self.show_thinking.setChecked(self._default_show_thinking)
        toggle_row.addWidget(self.show_thinking)

        toggle_row.addStretch()
        root.addLayout(toggle_row)

        root.addStretch()

        # ===== 按钮 =====
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("primary_btn")
        self.save_btn.setProperty("primary", True)
        self.save_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.save_btn)

        root.addLayout(btn_row)

    def apply_to_conversation(self) -> None:
        """Write UI values back into the conversation instance."""
        self._conversation.title = (self.title_edit.text() or "").strip() or self._conversation.title

        # Update provider/model from dialog
        provider_id = self.provider_combo.currentData() or ""
        model = self.model_combo.currentText().strip()
        mode_slug = self.mode_combo.currentData() if hasattr(self, "mode_combo") else None
        if provider_id:
            self._conversation.provider_id = provider_id
        if model:
            self._conversation.model = model
        if isinstance(mode_slug, str) and mode_slug.strip():
            self._conversation.mode = mode_slug.strip()

        settings = dict(self._conversation.settings or {})

        settings["system_prompt"] = (self.system_prompt_edit.toPlainText() or "").strip()
        settings["max_context_messages"] = int(self.context_limit.value())
        settings["temperature"] = float(self.temperature.value())
        settings["top_p"] = float(self.top_p.value())
        settings["max_tokens"] = int(self.max_tokens.value())
        settings["stream"] = bool(self.stream_enabled.isChecked())
        settings["show_thinking"] = bool(self.show_thinking.isChecked())

        # Summary/compression settings
        if hasattr(self, "summary_model_combo"):
            summary_model = self.summary_model_combo.currentText().strip()
            if summary_model:
                settings["summary_model"] = summary_model
            else:
                settings.pop("summary_model", None)

        # Prompt optimizer settings
        if hasattr(self, "prompt_optimizer_model_combo"):
            opt_model = self.prompt_optimizer_model_combo.currentText().strip()
            if opt_model:
                settings["prompt_optimizer_model"] = opt_model
            else:
                settings.pop("prompt_optimizer_model", None)

        if hasattr(self, "prompt_optimizer_system_prompt_edit"):
            opt_sys = (self.prompt_optimizer_system_prompt_edit.toPlainText() or "").strip()
            if opt_sys:
                settings["prompt_optimizer_system_prompt"] = opt_sys
            else:
                settings.pop("prompt_optimizer_system_prompt", None)

        if hasattr(self, "summary_system_prompt_edit"):
            summary_sys = (self.summary_system_prompt_edit.toPlainText() or "").strip()
            if summary_sys:
                settings["summary_system_prompt"] = summary_sys
            else:
                settings.pop("summary_system_prompt", None)

        if hasattr(self, "summary_include_tool_details"):
            if bool(self.summary_include_tool_details.isChecked()):
                settings["summary_include_tool_details"] = True
            else:
                settings.pop("summary_include_tool_details", None)

        # Clean empty values
        if not settings.get("system_prompt"):
            settings.pop("system_prompt", None)
        if settings.get("max_context_messages") == 0:
            settings.pop("max_context_messages", None)

        self._conversation.settings = settings

    def _on_provider_changed(self, index: int):
        """Populate model combo when provider changes."""
        current_model = self.model_combo.currentText().strip()
        current_summary_model = (
            self.summary_model_combo.currentText().strip() if hasattr(self, "summary_model_combo") else ""
        )
        current_opt_model = (
            self.prompt_optimizer_model_combo.currentText().strip() if hasattr(self, "prompt_optimizer_model_combo") else ""
        )

        self.model_combo.clear()
        if hasattr(self, "summary_model_combo"):
            self.summary_model_combo.clear()
        if hasattr(self, "prompt_optimizer_model_combo"):
            self.prompt_optimizer_model_combo.clear()

        if 0 <= index < len(self._providers):
            provider = self._providers[index]
            for model in provider.models:
                self.model_combo.addItem(model)
                if hasattr(self, "summary_model_combo"):
                    self.summary_model_combo.addItem(model)
                if hasattr(self, "prompt_optimizer_model_combo"):
                    self.prompt_optimizer_model_combo.addItem(model)

            if current_model:
                self.model_combo.setCurrentText(current_model)
            elif provider.default_model:
                idx = self.model_combo.findText(provider.default_model)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
                else:
                    self.model_combo.setCurrentText(provider.default_model)

            if hasattr(self, "summary_model_combo"):
                if current_summary_model:
                    self.summary_model_combo.setCurrentText(current_summary_model)
                elif provider.default_model:
                    self.summary_model_combo.setCurrentText(provider.default_model)

            if hasattr(self, "prompt_optimizer_model_combo"):
                if current_opt_model:
                    self.prompt_optimizer_model_combo.setCurrentText(current_opt_model)
                elif provider.default_model:
                    self.prompt_optimizer_model_combo.setCurrentText(provider.default_model)
