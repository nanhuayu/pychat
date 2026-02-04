from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QFormLayout,
    QComboBox,
    QVBoxLayout as QVBox,
    QCheckBox,
)


class AppearancePage(QWidget):
    page_emoji = "🎨"
    page_title = "外观设置"

    def __init__(self, *, theme: str = "dark", show_stats: bool = True, show_thinking: bool = True, log_stream: bool = False, parent=None):
        super().__init__(parent)
        self._setup_ui(theme, show_stats, show_thinking, log_stream)

    def _setup_ui(self, theme: str, show_stats: bool, show_thinking: bool, log_stream: bool) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        theme_group = QGroupBox("主题")
        theme_layout = QFormLayout(theme_group)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["深色", "浅色"])
        t = (theme or "dark").lower()
        self.theme_combo.setCurrentIndex(1 if t == "light" else 0)
        theme_layout.addRow("界面主题:", self.theme_combo)
        layout.addWidget(theme_group)

        display_group = QGroupBox("显示")
        display_layout = QVBox(display_group)

        self.stats_check = QCheckBox("显示统计面板")
        self.stats_check.setChecked(bool(show_stats))
        display_layout.addWidget(self.stats_check)

        self.thinking_check = QCheckBox("显示思考过程")
        self.thinking_check.setChecked(bool(show_thinking))
        display_layout.addWidget(self.thinking_check)

        self.log_check = QCheckBox("记录流式日志 (Debug)")
        self.log_check.setChecked(bool(log_stream))
        display_layout.addWidget(self.log_check)

        layout.addWidget(display_group)
        layout.addStretch()

    def collect(self) -> dict:
        return {
            "theme": "light" if self.theme_combo.currentIndex() == 1 else "dark",
            "show_stats": bool(self.stats_check.isChecked()),
            "show_thinking": bool(self.thinking_check.isChecked()),
            "log_stream": bool(self.log_check.isChecked()),
        }
