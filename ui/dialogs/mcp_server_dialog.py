"""
Dialog for managing MCP servers.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QCheckBox, QMessageBox, QWidget, QFormLayout, QTextEdit
)
from PyQt6.QtCore import Qt
from typing import List, Optional
import json

from models.mcp_server import McpServerConfig
from services.storage_service import StorageService

class McpServerEditDialog(QDialog):
    def __init__(self, config: Optional[McpServerConfig] = None, parent=None):
        super().__init__(parent)
        self.config = config
        self.setup_ui()
        if config:
            self.load_config(config)

    def setup_ui(self):
        self.setObjectName("mcpServerDialog")
        self.setWindowTitle("MCP Server Configuration")
        self.setMinimumWidth(400)
        
        layout = QFormLayout(self)
        
        self.name_edit = QLineEdit()
        self.command_edit = QLineEdit()
        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText('Space separated or JSON array for complex args')
        self.env_edit = QTextEdit()
        self.env_edit.setPlaceholderText('KEY=VALUE (one per line)')
        self.env_edit.setMaximumHeight(100)
        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(True)

        layout.addRow("Name:", self.name_edit)
        layout.addRow("Command:", self.command_edit)
        layout.addRow("Args:", self.args_edit)
        layout.addRow("Env Vars:", self.env_edit)
        layout.addRow("", self.enabled_check)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addRow(btn_layout)

    def load_config(self, config: McpServerConfig):
        self.name_edit.setText(config.name)
        self.command_edit.setText(config.command)
        if config.args:
            self.args_edit.setText(json.dumps(config.args))
        
        env_str = []
        for k, v in config.env.items():
            env_str.append(f"{k}={v}")
        self.env_edit.setText("\n".join(env_str))
        self.enabled_check.setChecked(config.enabled)

    def get_config(self) -> McpServerConfig:
        name = self.name_edit.text().strip() or "Unnamed"
        command = self.command_edit.text().strip()
        
        args_text = self.args_edit.text().strip()
        args = []
        if args_text:
            if args_text.startswith("["):
                try:
                    args = json.loads(args_text)
                except:
                    args = args_text.split()
            else:
                args = args_text.split()
        
        env = {}
        env_lines = self.env_edit.toPlainText().split('\n')
        for line in env_lines:
            if '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
                
        return McpServerConfig(
            name=name,
            command=command,
            args=args,
            env=env,
            enabled=self.enabled_check.isChecked()
        )


class McpSettingsWidget(QWidget):
    def __init__(self, storage_service: Optional[StorageService] = None, parent=None):
        super().__init__(parent)
        self.storage = storage_service or StorageService()
        self.servers = self.storage.load_mcp_servers()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("MCP Servers"))
        add_btn = QPushButton("+ Add Server")
        add_btn.clicked.connect(self.add_server)
        header.addWidget(add_btn)
        layout.addLayout(header)
        
        # List
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.edit_server)
        layout.addWidget(self.list_widget)
        
        self.refresh_list()
        
        # Help text
        layout.addWidget(QLabel("Double-click to edit. Use 'mcp' Python package for connection."))

    def refresh_list(self):
        self.list_widget.clear()
        for s in self.servers:
            status = "✅" if s.enabled else "❌"
            item = QListWidgetItem(f"{status} {s.name} ({s.command})")
            item.setData(Qt.ItemDataRole.UserRole, s)
            self.list_widget.addItem(item)

    def add_server(self):
        dialog = McpServerEditDialog(parent=self)
        if dialog.exec():
            new_server = dialog.get_config()
            self.servers.append(new_server)
            self.save_and_refresh()

    def edit_server(self, item):
        server = item.data(Qt.ItemDataRole.UserRole)
        dialog = McpServerEditDialog(config=server, parent=self)
        if dialog.exec():
            # Update object in place or replace? Replace.
            new_config = dialog.get_config()
            idx = self.servers.index(server)
            self.servers[idx] = new_config
            self.save_and_refresh()

    def save_and_refresh(self):
        self.storage.save_mcp_servers(self.servers)
        self.refresh_list()
