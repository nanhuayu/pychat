"""
Settings dialog for application configuration - Chinese UI
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QPushButton, QLabel, QListWidgetItem, QMessageBox,
    QGroupBox, QCheckBox, QComboBox, QFormLayout
)
from PyQt6.QtCore import pyqtSignal
from typing import List

from models.provider import Provider
from services.provider_service import ProviderService
from .provider_dialog import ProviderDialog


class ProviderListItem(QListWidgetItem):
    def __init__(self, provider: Provider):
        super().__init__()
        self.provider = provider
        self._update_display()
    
    def _update_display(self):
        status = "✓" if self.provider.enabled else "○"
        self.setText(f"{status} {self.provider.name}")
        models_count = len(self.provider.models)
        self.setToolTip(f"API: {self.provider.api_base}\n模型数: {models_count}")


class SettingsDialog(QDialog):
    """Application settings dialog"""
    
    providers_changed = pyqtSignal()
    
    def __init__(self, providers: List[Provider], current_settings: dict | None = None, parent=None):
        super().__init__(parent)
        self.providers = list(providers)
        self.provider_service = ProviderService()
        self._current_settings = current_settings or {}
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWindowTitle("设置")
        self.setMinimumWidth(550)
        self.setMinimumHeight(450)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        title = QLabel("设置")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Providers section
        providers_group = QGroupBox("LLM 服务商")
        providers_layout = QVBoxLayout(providers_group)
        
        self.provider_list = QListWidget()
        self.provider_list.setMinimumHeight(180)
        self._refresh_provider_list()
        providers_layout.addWidget(self.provider_list)
        
        provider_btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._add_provider)
        provider_btn_layout.addWidget(add_btn)
        
        edit_btn = QPushButton("编辑")
        edit_btn.clicked.connect(self._edit_provider)
        provider_btn_layout.addWidget(edit_btn)
        
        delete_btn = QPushButton("删除")
        delete_btn.setProperty("danger", True)
        delete_btn.clicked.connect(self._delete_provider)
        provider_btn_layout.addWidget(delete_btn)
        
        provider_btn_layout.addStretch()
        
        defaults_btn = QPushButton("添加默认服务商")
        defaults_btn.clicked.connect(self._add_default_providers)
        provider_btn_layout.addWidget(defaults_btn)
        
        providers_layout.addLayout(provider_btn_layout)
        layout.addWidget(providers_group)
        
        # Appearance
        appearance_group = QGroupBox("外观")
        appearance_layout = QFormLayout(appearance_group)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["深色", "浅色"])
        theme = (self._current_settings.get('theme') or 'dark').lower()
        self.theme_combo.setCurrentIndex(1 if theme == 'light' else 0)
        appearance_layout.addRow("主题:", self.theme_combo)
        
        self.stats_visible_check = QCheckBox("显示统计面板")
        self.stats_visible_check.setChecked(bool(self._current_settings.get('show_stats', True)))
        appearance_layout.addRow("", self.stats_visible_check)

        self.thinking_visible_check = QCheckBox("显示思考过程")
        self.thinking_visible_check.setChecked(bool(self._current_settings.get('show_thinking', True)))
        appearance_layout.addRow("", self.thinking_visible_check)

        self.stream_log_check = QCheckBox("记录流式日志 (debug)")
        self.stream_log_check.setChecked(bool(self._current_settings.get('log_stream', False)))
        appearance_layout.addRow("", self.stream_log_check)
        
        layout.addWidget(appearance_group)
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("保存")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self.accept)
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)
    
    def _refresh_provider_list(self):
        self.provider_list.clear()
        for provider in self.providers:
            item = ProviderListItem(provider)
            self.provider_list.addItem(item)
    
    def _add_provider(self):
        dialog = ProviderDialog(parent=self)
        if dialog.exec():
            provider = dialog.get_provider()
            self.providers.append(provider)
            self._refresh_provider_list()
            self.providers_changed.emit()
    
    def _edit_provider(self):
        item = self.provider_list.currentItem()
        if not isinstance(item, ProviderListItem):
            QMessageBox.information(self, "提示", "请先选择一个服务商")
            return
        
        dialog = ProviderDialog(item.provider, self)
        if dialog.exec():
            item._update_display()
            self.providers_changed.emit()
    
    def _delete_provider(self):
        item = self.provider_list.currentItem()
        if not isinstance(item, ProviderListItem):
            QMessageBox.information(self, "提示", "请先选择一个服务商")
            return
        
        reply = QMessageBox.question(
            self, '删除服务商',
            f'确定要删除 "{item.provider.name}" 吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.providers.remove(item.provider)
            self._refresh_provider_list()
            self.providers_changed.emit()
    
    def _add_default_providers(self):
        defaults = self.provider_service.create_default_providers()
        existing_names = {p.name for p in self.providers}
        added = 0
        
        for provider in defaults:
            if provider.name not in existing_names:
                self.providers.append(provider)
                added += 1
        
        self._refresh_provider_list()
        
        if added > 0:
            QMessageBox.information(
                self, "已添加",
                f"已添加 {added} 个默认服务商。\n请记得配置对应的 API Key。"
            )
            self.providers_changed.emit()
        else:
            QMessageBox.information(self, "提示", "所有默认服务商已存在")
    
    def get_providers(self) -> List[Provider]:
        return self.providers
    
    def get_show_stats(self) -> bool:
        return self.stats_visible_check.isChecked()

    def get_theme(self) -> str:
        return 'light' if self.theme_combo.currentIndex() == 1 else 'dark'

    def get_show_thinking(self) -> bool:
        return self.thinking_visible_check.isChecked()

    def get_log_stream(self) -> bool:
        return self.stream_log_check.isChecked()
