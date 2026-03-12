"""Conversation settings dialog (per-conversation overrides)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QComboBox,
)
from typing import List, Optional

from models.conversation import Conversation
from models.provider import Provider
from core.modes.manager import ModeManager
from ui.utils.form_builder import FormSection


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

        s = conversation.settings or {}

        # ===== 基本信息 =====
        basic = FormSection("基本信息")
        self.title_edit = basic.add_line_edit("名称", text=conversation.title or "", object_name="conv_title")
        self.system_prompt_edit = basic.add_text_edit(
            "系统提示", text=s.get("system_prompt", "") or "",
            placeholder="例如：你是一个严谨的助手...（可选）", object_name="conv_system_prompt",
        )
        root.addWidget(basic.group)

        # ===== 模型设置 =====
        model_sec = FormSection("模型设置")
        self.provider_combo = model_sec.add_combo("服务商", object_name="conv_provider")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.model_combo = model_sec.add_combo("模型", editable=True, object_name="conv_model")

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("conv_mode")
        try:
            mm = ModeManager(None)
            for m in mm.list_modes():
                self.mode_combo.addItem(m.name, m.slug)
        except Exception:
            self.mode_combo.addItem("Chat", "chat")
            self.mode_combo.addItem("Agent", "agent")
        try:
            cur_slug = str(getattr(conversation, "mode", "chat") or "chat")
            idx = self.mode_combo.findData(cur_slug)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
        except Exception:
            pass
        model_sec.form.addRow("模式", self.mode_combo)

        for p in self._providers:
            self.provider_combo.addItem(p.name, p.id)
        for i, p in enumerate(self._providers):
            if p.id == conversation.provider_id:
                self.provider_combo.setCurrentIndex(i)
                break
        if conversation.model:
            self.model_combo.setCurrentText(conversation.model)
        root.addWidget(model_sec.group)

        # ===== 压缩/优化 =====
        comp = FormSection("压缩/优化")
        self.summary_model_combo = comp.add_combo(
            "压缩模型", editable=True,
            current_text=str(s.get("summary_model", "") or ""),
            object_name="conv_summary_model",
        )
        self.summary_include_tool_details = comp.add_checkbox(
            "包含工具详情（更耗 token）", row_label="工具信息",
            checked=bool(s.get("summary_include_tool_details", False)),
            object_name="conv_summary_include_tool_details",
        )
        self.summary_system_prompt_edit = comp.add_text_edit(
            "压缩System", text=s.get("summary_system_prompt", "") or "",
            placeholder="可选：用于压缩/总结请求的 system prompt（留空使用内置简洁模板）",
            max_height=70, object_name="conv_summary_system_prompt",
        )
        self.prompt_optimizer_model_combo = comp.add_combo(
            "优化模型", editable=True,
            current_text=str(s.get("prompt_optimizer_model", "") or ""),
            object_name="conv_prompt_optimizer_model",
        )
        self.prompt_optimizer_system_prompt_edit = comp.add_text_edit(
            "优化System", text=s.get("prompt_optimizer_system_prompt", "") or "",
            placeholder="可选：用于'优化提示词'请求的 system prompt（留空使用内置模板）",
            max_height=70, object_name="conv_prompt_optimizer_system_prompt",
        )
        root.addWidget(comp.group)


        # ===== 采样参数 =====
        temp_val = s.get("temperature")
        top_p_val = s.get("top_p")
        params = FormSection("采样参数")
        self.context_limit = params.add_spin(
            "上下文消息数", value=int(s.get("max_context_messages", 0) or 0),
            range=(0, 200), tooltip="0 表示不限制", object_name="conv_context_limit",
        )
        self.temperature = params.add_double_spin(
            "温度", value=float(temp_val) if isinstance(temp_val, (int, float)) else 0.70,
            range=(0.0, 2.0), object_name="conv_temperature",
        )
        self.top_p = params.add_double_spin(
            "Top P", value=float(top_p_val) if isinstance(top_p_val, (int, float)) else 1.00,
            object_name="conv_top_p",
        )
        self.max_tokens = params.add_spin(
            "最大 Token", value=int(s.get("max_tokens") or 0),
            range=(0, 200000), step=256, tooltip="最大输出 Token 数",
            object_name="conv_max_tokens",
        )
        root.addWidget(params.group)

        # ===== 功能开关 =====
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(16)

        self.stream_enabled = QCheckBox("流式输出")
        self.stream_enabled.setObjectName("conv_stream")
        self.stream_enabled.setChecked(bool(s.get("stream", True)))
        toggle_row.addWidget(self.stream_enabled)

        self.show_thinking = QCheckBox("显示思考")
        self.show_thinking.setObjectName("conv_show_thinking")
        show_thinking_val = s.get("show_thinking")
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
