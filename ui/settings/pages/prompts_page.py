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
        self._setup_ui(prompts, prompt_optimizer)

    def _setup_ui(self, prompts: PromptsConfig, prompt_optimizer: PromptOptimizerConfig) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<h2>提示词</h2>"))

        sys_group = QGroupBox("System Prompt 模板")
        sys_form = QFormLayout(sys_group)
        sys_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        sys_form.setHorizontalSpacing(10)
        sys_form.setVerticalSpacing(6)

        self.default_system_prompt_edit = QTextEdit()
        self.default_system_prompt_edit.setAcceptRichText(False)
        self.default_system_prompt_edit.setMaximumHeight(120)
        self.default_system_prompt_edit.setPlaceholderText("可选：替换默认 System Prompt（Chat/Ask 等；模式 roleDefinition 优先级更高）")
        self.default_system_prompt_edit.setText((prompts.default_system_prompt or "").strip())
        sys_form.addRow("默认提示词", self.default_system_prompt_edit)

        self.base_role_definition_edit = QTextEdit()
        self.base_role_definition_edit.setAcceptRichText(False)
        self.base_role_definition_edit.setMaximumHeight(110)
        self.base_role_definition_edit.setPlaceholderText("可选：旧字段（留空使用上面的“默认提示词”或内置）")
        self.base_role_definition_edit.setText((prompts.base_role_definition or "").strip())
        sys_form.addRow("基础角色定义", self.base_role_definition_edit)

        self.agent_tool_guidelines_edit = QTextEdit()
        self.agent_tool_guidelines_edit.setAcceptRichText(False)
        self.agent_tool_guidelines_edit.setMaximumHeight(140)
        self.agent_tool_guidelines_edit.setPlaceholderText("可选：替换 Agent 模式的工具使用指南（留空使用内置）")
        self.agent_tool_guidelines_edit.setText((prompts.agent_tool_guidelines or "").strip())
        sys_form.addRow("Agent 工具指南", self.agent_tool_guidelines_edit)

        layout.addWidget(sys_group)

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
        opt_form.addRow("System Prompt", self.prompt_opt_system_edit)

        def _on_template_changed(_i: int) -> None:
            name = self.prompt_opt_template_combo.currentText()
            self.prompt_opt_system_edit.setText((templates.get(name, "") or "").strip())

        self.prompt_opt_template_combo.currentIndexChanged.connect(_on_template_changed)

        layout.addWidget(opt_group)

        hint = QLabel("提示：这里配置的是全局默认模板；对话级别仍可在“对话设置”中覆盖。")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        layout.addStretch()

        self._templates = templates

    def collect_prompts(self) -> PromptsConfig:
        return PromptsConfig.from_dict(
            {
                "default_system_prompt": (self.default_system_prompt_edit.toPlainText() or "").strip(),
                "base_role_definition": (self.base_role_definition_edit.toPlainText() or "").strip(),
                "agent_tool_guidelines": (self.agent_tool_guidelines_edit.toPlainText() or "").strip(),
                # include_environment/include_state remain default True for now
            }
        )

    def collect_prompt_optimizer(self) -> PromptOptimizerConfig:
        sel = (self.prompt_opt_template_combo.currentText() or "default").strip() or "default"
        content = (self.prompt_opt_system_edit.toPlainText() or "").strip()
        templates = dict(self._templates or {})
        templates[sel] = content
        return PromptOptimizerConfig(selected_template=sel, templates=templates)
