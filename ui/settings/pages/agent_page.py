from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QCheckBox

from core.config.schema import PermissionsConfig


class AgentPermissionsPage(QWidget):
    page_emoji = "🛡️"
    page_title = "Agent & 权限"

    def __init__(self, permissions: PermissionsConfig, parent=None):
        super().__init__(parent)
        self._setup_ui(permissions)

    def _setup_ui(self, permissions: PermissionsConfig) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<h2>Agent 与 权限设置</h2>"))

        perm_group = QGroupBox("自动授权设置")
        perm_layout = QVBoxLayout(perm_group)

        self.auto_read_check = QCheckBox("自动允许读取文件 (read_file, ls, grep)")
        self.auto_read_check.setToolTip("启用后，读取文件的操作将不再询问确认")
        self.auto_read_check.setChecked(bool(permissions.auto_approve_read))
        perm_layout.addWidget(self.auto_read_check)

        self.auto_edit_check = QCheckBox("自动允许编辑文件 (write, edit, delete)")
        self.auto_edit_check.setToolTip("启用后，修改文件的操作将不再询问确认 (请谨慎开启)")
        self.auto_edit_check.setChecked(bool(permissions.auto_approve_edit))
        perm_layout.addWidget(self.auto_edit_check)

        self.auto_cmd_check = QCheckBox("自动允许执行命令 (shell_exec)")
        self.auto_cmd_check.setToolTip("启用后，执行 Shell 命令将不再询问确认 (极度危险!)")
        self.auto_cmd_check.setChecked(bool(permissions.auto_approve_command))
        perm_layout.addWidget(self.auto_cmd_check)

        layout.addWidget(perm_group)

        layout.addStretch()

    def collect(self) -> PermissionsConfig:
        return PermissionsConfig(
            auto_approve_read=bool(self.auto_read_check.isChecked()),
            auto_approve_edit=bool(self.auto_edit_check.isChecked()),
            auto_approve_command=bool(self.auto_cmd_check.isChecked()),
        )
