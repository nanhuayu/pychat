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
    QPushButton,
    QHBoxLayout,
    QLineEdit,
)

from core.config.schema import PromptsConfig, PromptOptimizerConfig
from core.prompts.templates import DEFAULT_PROMPT_OPTIMIZER_SYSTEM_PROMPT


class PromptsPage(QWidget):
    page_emoji = "📝"
    page_title = "提示词"

    def __init__(
        self,
        prompts: PromptsConfig,
        prompt_optimizer: PromptOptimizerConfig,
        prompt_optimizer_model: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._original_prompts = prompts
        self._setup_ui(prompts, prompt_optimizer, prompt_optimizer_model)

    def _setup_ui(
        self,
        prompts: PromptsConfig,
        prompt_optimizer: PromptOptimizerConfig,
        prompt_optimizer_model: str,
    ) -> None:
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

        self.prompt_opt_model_edit = QLineEdit()
        self.prompt_opt_model_edit.setPlaceholderText("留空时跟随当前对话模型")
        self.prompt_opt_model_edit.setText((prompt_optimizer_model or "").strip())
        opt_form.addRow("优化模型", self.prompt_opt_model_edit)

        self.prompt_opt_system_edit = QTextEdit()
        self.prompt_opt_system_edit.setAcceptRichText(False)
        self.prompt_opt_system_edit.setMaximumHeight(140)
        self.prompt_opt_system_edit.setPlaceholderText("留空使用内置默认模板")
        initial = templates.get(self.prompt_opt_template_combo.currentText(), "")
        self.prompt_opt_system_edit.setText((initial or "").strip())
        opt_form.addRow("优化器提示词", self.prompt_opt_system_edit)

        button_row_widget = QWidget()
        button_row = QHBoxLayout(button_row_widget)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addStretch()

        self.prompt_opt_default_btn = QPushButton("填入内置默认模板")
        self.prompt_opt_default_btn.clicked.connect(self._load_builtin_template)
        button_row.addWidget(self.prompt_opt_default_btn)

        self.prompt_opt_clear_btn = QPushButton("清空并继续使用内置模板")
        self.prompt_opt_clear_btn.clicked.connect(lambda: self.prompt_opt_system_edit.setPlainText(""))
        button_row.addWidget(self.prompt_opt_clear_btn)

        opt_form.addRow("", button_row_widget)

        def _on_template_changed(_i: int) -> None:
            name = self.prompt_opt_template_combo.currentText()
            self.prompt_opt_system_edit.setText((templates.get(name, "") or "").strip())

        self.prompt_opt_template_combo.currentIndexChanged.connect(_on_template_changed)

        layout.addWidget(opt_group)

        hint = QLabel("提示：这里只保留一份可编辑的优化提示词。留空时自动使用内置默认模板；对话级别仍可在“对话设置”中覆盖。")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        layout.addStretch()

        self._templates = templates

    def _load_builtin_template(self) -> None:
        self.prompt_opt_system_edit.setPlainText(DEFAULT_PROMPT_OPTIMIZER_SYSTEM_PROMPT.strip())

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

    def collect_prompt_optimizer_model(self) -> str:
        return (self.prompt_opt_model_edit.text() or "").strip()
