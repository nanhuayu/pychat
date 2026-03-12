"""Skills management settings page."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QTextEdit, QPushButton,
)
from PyQt6.QtCore import Qt

from core.skills import SkillsManager


class SkillsPage(QWidget):
    page_emoji = "📚"
    page_title = "技能管理"

    def __init__(self, work_dir: str = ".", parent=None):
        super().__init__(parent)
        self._manager = SkillsManager(work_dir)
        self._setup_ui()
        self._refresh_list()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<h2>技能管理</h2>"))
        layout.addWidget(QLabel(
            "技能 (Skills) 是可复用的指令文件 (.md)，激活后会注入到系统提示中。\n"
            "目录: ~/.PyChat/skills/ (全局)  |  .pychat/skills/ (项目)"
        ))

        body = QHBoxLayout()

        # Left: skill list
        left = QVBoxLayout()
        self.skill_list = QListWidget()
        self.skill_list.currentItemChanged.connect(self._on_selection_changed)
        left.addWidget(QLabel("已发现的技能:"))
        left.addWidget(self.skill_list)

        reload_btn = QPushButton("🔄 重新扫描")
        reload_btn.clicked.connect(self._refresh_list)
        left.addWidget(reload_btn)
        body.addLayout(left, 1)

        # Right: content preview
        right = QVBoxLayout()
        self.source_label = QLabel("")
        self.source_label.setWordWrap(True)
        right.addWidget(self.source_label)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("选择左侧技能查看内容")
        right.addWidget(self.preview)
        body.addLayout(right, 2)

        layout.addLayout(body)

    def _refresh_list(self) -> None:
        self.skill_list.clear()
        self.preview.clear()
        self.source_label.setText("")
        self._manager.reload()
        for skill in self._manager.list_skills():
            item = QListWidgetItem(skill.name)
            item.setData(Qt.ItemDataRole.UserRole, skill.name)
            self.skill_list.addItem(item)

    def _on_selection_changed(self, current: QListWidgetItem | None, _prev) -> None:
        if not current:
            self.preview.clear()
            self.source_label.setText("")
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        skill = self._manager.get(name)
        if skill:
            self.source_label.setText(f"来源: {skill.source}")
            self.preview.setPlainText(skill.content)
        else:
            self.preview.clear()
            self.source_label.setText("")
