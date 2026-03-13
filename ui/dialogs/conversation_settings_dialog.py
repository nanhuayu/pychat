"""Conversation settings dialog (per-conversation overrides)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QComboBox,
    QLabel,
)
from typing import List, Optional

from core.config import AppConfig, load_app_config
from models.conversation import Conversation
from models.provider import Provider
from core.modes.manager import ModeManager
from core.prompts.system_builder import resolve_base_system_prompt_text
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
        try:
            self._app_config = load_app_config()
        except Exception:
            self._app_config = AppConfig()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        s = conversation.settings or {}
        self._system_prompt_base_text = self._compute_base_system_prompt()
        self._system_prompt_display_text = (s.get("system_prompt", "") or "").strip() or self._system_prompt_base_text

        # ===== 基本信息 =====
        basic = FormSection("基本信息")
        self.title_edit = basic.add_line_edit("名称", text=conversation.title or "", object_name="conv_title")
        self.system_prompt_edit = basic.add_text_edit(
            "系统提示", text=self._system_prompt_display_text,
            placeholder="显示当前生效的基础 system prompt，可直接修改", object_name="conv_system_prompt",
        )
        self.system_prompt_note = QLabel("当前显示的是该模式下生效的基础 system prompt。保持不改时不会额外保存对话级覆盖。")
        self.system_prompt_note.setWordWrap(True)
        self.system_prompt_note.setProperty("muted", True)
        basic.form.addRow("", self.system_prompt_note)
        root.addWidget(basic.group)

        # ===== 模型设置 =====
        model_sec = FormSection("模型设置")
        self.provider_combo = model_sec.add_combo("服务商", object_name="conv_provider")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.model_combo = model_sec.add_combo("模型", editable=True, object_name="conv_model")

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("conv_mode")
        self.mode_combo.blockSignals(True)
        try:
            mm = ModeManager(getattr(conversation, "work_dir", "") or None)
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
        self.mode_combo.blockSignals(False)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
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

        self.enable_mcp = QCheckBox("启用 MCP 工具")
        self.enable_mcp.setObjectName("conv_enable_mcp")
        self.enable_mcp.setChecked(bool(s.get("enable_mcp", False)))
        toggle_row.addWidget(self.enable_mcp)

        self.enable_search = QCheckBox("启用网络搜索")
        self.enable_search.setObjectName("conv_enable_search")
        self.enable_search.setChecked(bool(s.get("enable_search", False)))
        toggle_row.addWidget(self.enable_search)

        toggle_row.addStretch()
        root.addLayout(toggle_row)

        self._on_mode_changed(self.mode_combo.currentIndex())

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
        settings["enable_mcp"] = bool(self.enable_mcp.isChecked())
        settings["enable_search"] = bool(self.enable_search.isChecked())

        for key in (
            "summary_model",
            "summary_include_tool_details",
            "summary_system_prompt",
            "prompt_optimizer_model",
            "prompt_optimizer_system_prompt",
        ):
            settings.pop(key, None)

        # Clean empty values
        system_prompt_text = (self.system_prompt_edit.toPlainText() or "").strip()
        if system_prompt_text and system_prompt_text != self._system_prompt_base_text:
            settings["system_prompt"] = system_prompt_text
        else:
            settings.pop("system_prompt", None)
        if settings.get("max_context_messages") == 0:
            settings.pop("max_context_messages", None)

        self._conversation.settings = settings

    def _on_mode_changed(self, index: int) -> None:
        if not hasattr(self, "enable_mcp") or not hasattr(self, "enable_search") or not hasattr(self, "show_thinking"):
            return
        slug = str(self.mode_combo.itemData(index) or "chat").strip().lower()
        settings = self._conversation.settings or {}
        try:
            mm = ModeManager(getattr(self._conversation, "work_dir", "") or None)
            mode = mm.get(slug)
            groups = set(mode.group_names())
        except Exception:
            groups = set()

        previous_base = self._system_prompt_base_text
        self._system_prompt_base_text = self._compute_base_system_prompt(slug)
        current_text = (self.system_prompt_edit.toPlainText() or "").strip()
        if not current_text or current_text == previous_base:
            self.system_prompt_edit.blockSignals(True)
            try:
                self.system_prompt_edit.setPlainText(self._system_prompt_base_text)
            finally:
                self.system_prompt_edit.blockSignals(False)

        allow_mcp = bool({"mcp", "command", "edit"} & groups)
        allow_search = bool("search" in groups)
        default_mcp = allow_mcp
        default_search = allow_search
        default_thinking = bool({"command", "edit"} & groups)

        self.enable_mcp.setEnabled(allow_mcp)
        self.enable_search.setEnabled(allow_search)

        if not allow_mcp:
            self.enable_mcp.setChecked(False)
        elif "enable_mcp" not in settings:
            self.enable_mcp.setChecked(default_mcp)

        if not allow_search:
            self.enable_search.setChecked(False)
        elif "enable_search" not in settings:
            self.enable_search.setChecked(default_search)

        if "show_thinking" not in settings:
            self.show_thinking.setChecked(default_thinking if slug != "chat" else self._default_show_thinking)

    def _on_provider_changed(self, index: int):
        """Populate model combo when provider changes."""
        current_model = self.model_combo.currentText().strip()

        self.model_combo.clear()

        if 0 <= index < len(self._providers):
            provider = self._providers[index]
            for model in provider.models:
                self.model_combo.addItem(model)

            if current_model:
                self.model_combo.setCurrentText(current_model)
            elif provider.default_model:
                idx = self.model_combo.findText(provider.default_model)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
                else:
                    self.model_combo.setCurrentText(provider.default_model)

    def _compute_base_system_prompt(self, mode_slug: Optional[str] = None) -> str:
        conv = Conversation.from_dict(self._conversation.to_dict())
        if mode_slug:
            conv.mode = str(mode_slug or "chat") or "chat"
        return resolve_base_system_prompt_text(
            conversation=conv,
            app_config=self._app_config,
            default_work_dir=getattr(conv, "work_dir", ".") or ".",
            include_conversation_override=False,
        )
