from __future__ import annotations

from typing import Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QGroupBox,
    QFormLayout,
    QTextEdit,
    QComboBox,
)

from core.config.schema import PromptsConfig, PromptOptimizerConfig


class PromptsPage(QWidget):
    page_emoji = "📝"
    page_title = "提示词"

    def __init__(self, prompts: PromptsConfig, prompt_optimizer: PromptOptimizerConfig, parent=None):
        super().__init__(parent)
        self._original_prompts = prompts
        self._setup_ui(prompts, prompt_optimizer)

    def _setup_ui(self, prompts: PromptsConfig, prompt_optimizer: PromptOptimizerConfig) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<h2>提示词</h2>"))

        opt_group = QGroupBox("提示词优化（✨）")
        opt_form = QFormLayout(opt_group)
        opt_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        opt_form.setHorizontalSpacing(10)
        opt_form.setVerticalSpacing(6)

        self.prompt_opt_template_combo = QComboBox()
        templates: Dict[str, str] = dict(prompt_optimizer.templates or {})
        names = list(templates.keys())
        if not names:
            templates = {"default": ""}
            names = ["default"]

        self.prompt_opt_template_combo.addItems(names)
        sel = (prompt_optimizer.selected_template or "default").strip() or "default"
        idx = self.prompt_opt_template_combo.findText(sel)
        if idx >= 0:
            self.prompt_opt_template_combo.setCurrentIndex(idx)

        opt_form.addRow("模板", self.prompt_opt_template_combo)

        self.prompt_opt_system_edit = QTextEdit()
        self.prompt_opt_system_edit.setAcceptRichText(False)
        self.prompt_opt_system_edit.setMaximumHeight(140)
        self.prompt_opt_system_edit.setPlaceholderText("留空使用内置默认模板")
        initial = templates.get(self.prompt_opt_template_combo.currentText(), "")
        self.prompt_opt_system_edit.setText((initial or "").strip())
        opt_form.addRow("优化器提示词", self.prompt_opt_system_edit)

        def _on_template_changed(_i: int) -> None:
            name = self.prompt_opt_template_combo.currentText()
            self.prompt_opt_system_edit.setText((templates.get(name, "") or "").strip())

        self.prompt_opt_template_combo.currentIndexChanged.connect(_on_template_changed)

        layout.addWidget(opt_group)

        hint = QLabel("提示：这里配置的是全局优化模板；对话级别仍可在“对话设置”中覆盖。")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        layout.addStretch()

        self._templates = templates

    def collect_prompts(self) -> PromptsConfig:
        # System prompt templates are now primarily configured per-mode via modes.json.
        # This page intentionally does not overwrite those legacy/global fields.
        return self._original_prompts

    def collect_prompt_optimizer(self) -> PromptOptimizerConfig:
        sel = (self.prompt_opt_template_combo.currentText() or "default").strip() or "default"
        content = (self.prompt_opt_system_edit.toPlainText() or "").strip()
        templates = dict(self._templates or {})
        templates[sel] = content
        return PromptOptimizerConfig(selected_template=sel, templates=templates)
