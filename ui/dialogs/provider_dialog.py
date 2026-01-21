"""
Provider configuration dialog - Chinese UI
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QLabel, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QGroupBox, QSpinBox, QDoubleSpinBox,
    QTextEdit, QTabWidget, QWidget, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal
import asyncio
from typing import Optional, List

from models.provider import Provider
from services.provider_service import ProviderService


class ProviderDialog(QDialog):
    """Dialog for configuring an LLM provider"""
    
    models_updated = pyqtSignal(list)  # Emit when models are fetched
    
    def __init__(self, provider: Optional[Provider] = None, parent=None):
        super().__init__(parent)
        self.provider = provider or Provider()
        self.provider_service = ProviderService()
        self._setup_ui()
        self._load_provider()
    
    def _setup_ui(self):
        self.setWindowTitle("配置服务商")
        self.setMinimumWidth(480)
        self.setMinimumHeight(550)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        tabs = QTabWidget()
        
        # Basic tab
        basic_tab = QWidget()
        basic_layout = QVBoxLayout(basic_tab)
        basic_layout.setSpacing(10)
        
        # Provider info
        info_group = QGroupBox("服务商信息")
        info_layout = QFormLayout(info_group)
        info_layout.setSpacing(8)
        
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("如: OpenAI, Claude, Ollama")
        info_layout.addRow("名称:", self.name_input)
        
        self.api_base_input = QLineEdit()
        self.api_base_input.setPlaceholderText("https://api.openai.com/v1")
        info_layout.addRow("API 地址:", self.api_base_input)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-...")
        
        key_layout = QHBoxLayout()
        key_layout.addWidget(self.api_key_input)
        show_key_btn = QPushButton("👁")
        show_key_btn.setFixedWidth(32)
        show_key_btn.setCheckable(True)
        show_key_btn.toggled.connect(
            lambda c: self.api_key_input.setEchoMode(
                QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password))
        key_layout.addWidget(show_key_btn)
        info_layout.addRow("API Key:", key_layout)
        
        basic_layout.addWidget(info_group)
        
        # Model settings
        model_group = QGroupBox("模型设置")
        model_layout = QFormLayout(model_group)
        model_layout.setSpacing(8)
        
        # Model selector combo (editable)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(200)
        model_layout.addRow("默认模型:", self.model_combo)
        
        # Fetch button
        fetch_btn = QPushButton("获取可用模型")
        fetch_btn.clicked.connect(self._fetch_models)
        model_layout.addRow("", fetch_btn)
        
        self.models_label = QLabel("未加载模型")
        self.models_label.setWordWrap(True)
        self.models_label.setStyleSheet("color: #71717a; font-size: 11px;")
        model_layout.addRow("可用模型:", self.models_label)
        
        self.max_tokens_input = QSpinBox()
        self.max_tokens_input.setRange(1, 128000)
        self.max_tokens_input.setValue(4096)
        model_layout.addRow("最大 Token:", self.max_tokens_input)
        
        self.temperature_input = QDoubleSpinBox()
        self.temperature_input.setRange(0.0, 2.0)
        self.temperature_input.setSingleStep(0.1)
        self.temperature_input.setValue(0.7)
        model_layout.addRow("Temperature:", self.temperature_input)
        
        basic_layout.addWidget(model_group)
        
        # Capabilities
        caps_group = QGroupBox("功能支持")
        caps_layout = QVBoxLayout(caps_group)
        caps_layout.setSpacing(4)
        
        self.supports_vision_check = QCheckBox("支持视觉 (图片输入)")
        self.supports_vision_check.setChecked(True)
        caps_layout.addWidget(self.supports_vision_check)
        
        self.supports_thinking_check = QCheckBox("支持思考模式")
        caps_layout.addWidget(self.supports_thinking_check)
        
        self.enabled_check = QCheckBox("启用")
        self.enabled_check.setChecked(True)
        caps_layout.addWidget(self.enabled_check)
        
        basic_layout.addWidget(caps_group)
        basic_layout.addStretch()
        
        tabs.addTab(basic_tab, "基本")
        
        # Advanced tab
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)
        
        headers_group = QGroupBox("自定义请求头")
        headers_layout = QVBoxLayout(headers_group)
        
        headers_help = QLabel("添加自定义 HTTP 请求头")
        headers_help.setStyleSheet("color: #71717a; font-size: 11px;")
        headers_layout.addWidget(headers_help)
        
        self.headers_table = QTableWidget(0, 2)
        self.headers_table.setHorizontalHeaderLabels(["名称", "值"])
        self.headers_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.headers_table.setMaximumHeight(120)
        headers_layout.addWidget(self.headers_table)
        
        headers_btn_layout = QHBoxLayout()
        add_header_btn = QPushButton("添加")
        add_header_btn.clicked.connect(self._add_header_row)
        headers_btn_layout.addWidget(add_header_btn)
        remove_header_btn = QPushButton("删除")
        remove_header_btn.clicked.connect(self._remove_header_row)
        headers_btn_layout.addWidget(remove_header_btn)
        headers_btn_layout.addStretch()
        headers_layout.addLayout(headers_btn_layout)
        
        advanced_layout.addWidget(headers_group)
        
        format_group = QGroupBox("请求格式 (JSON)")
        format_layout = QVBoxLayout(format_group)
        
        format_help = QLabel("额外的请求 JSON 字段，如思考模式配置")
        format_help.setStyleSheet("color: #71717a; font-size: 11px;")
        format_layout.addWidget(format_help)
        
        self.request_format_input = QTextEdit()
        self.request_format_input.setPlaceholderText('{"key": "value"}')
        self.request_format_input.setMaximumHeight(80)
        format_layout.addWidget(self.request_format_input)
        
        advanced_layout.addWidget(format_group)
        advanced_layout.addStretch()
        
        tabs.addTab(advanced_tab, "高级")
        layout.addWidget(tabs)
        
        # Test connection
        test_layout = QHBoxLayout()
        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self._test_connection)
        test_layout.addWidget(test_btn)
        self.test_status = QLabel("")
        test_layout.addWidget(self.test_status)
        test_layout.addStretch()
        layout.addLayout(test_layout)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("保存")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)
    
    def _load_provider(self):
        self.name_input.setText(self.provider.name)
        self.api_base_input.setText(self.provider.api_base)
        self.api_key_input.setText(self.provider.api_key)
        self.max_tokens_input.setValue(self.provider.max_tokens)
        self.temperature_input.setValue(self.provider.temperature)
        self.supports_vision_check.setChecked(self.provider.supports_vision)
        self.supports_thinking_check.setChecked(self.provider.supports_thinking)
        self.enabled_check.setChecked(self.provider.enabled)
        
        # Load models into combo
        self.model_combo.clear()
        for model in self.provider.models:
            self.model_combo.addItem(model)
        if self.provider.default_model:
            idx = self.model_combo.findText(self.provider.default_model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentText(self.provider.default_model)
        
        if self.provider.models:
            display = ", ".join(self.provider.models[:8])
            if len(self.provider.models) > 8:
                display += f" ... (+{len(self.provider.models) - 8})"
            self.models_label.setText(display)
        
        for key, value in self.provider.custom_headers.items():
            self._add_header_row(key, value)
        
        if self.provider.request_format:
            import json
            self.request_format_input.setPlainText(
                json.dumps(self.provider.request_format, indent=2, ensure_ascii=False))
    
    def _add_header_row(self, key: str = "", value: str = ""):
        row = self.headers_table.rowCount()
        self.headers_table.insertRow(row)
        self.headers_table.setItem(row, 0, QTableWidgetItem(key))
        self.headers_table.setItem(row, 1, QTableWidgetItem(value))
    
    def _remove_header_row(self):
        row = self.headers_table.currentRow()
        if row >= 0:
            self.headers_table.removeRow(row)
    
    def _fetch_models(self):
        self._save_to_provider()
        
        valid, msg = self.provider_service.validate_provider(self.provider)
        if not valid:
            QMessageBox.warning(self, "验证错误", msg)
            return
        
        self.models_label.setText("正在获取模型...")
        
        async def fetch():
            return await self.provider_service.fetch_models(self.provider)
        
        try:
            loop = asyncio.new_event_loop()
            models = loop.run_until_complete(fetch())
            loop.close()
            
            if models:
                self.provider.models = models
                # Update combo box
                current = self.model_combo.currentText()
                self.model_combo.clear()
                for model in models:
                    self.model_combo.addItem(model)
                # Restore selection
                idx = self.model_combo.findText(current)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
                
                display = ", ".join(models[:8])
                if len(models) > 8:
                    display += f" ... (+{len(models) - 8})"
                self.models_label.setText(display)
            else:
                self.models_label.setText("未找到模型")
        except Exception as e:
            self.models_label.setText(f"错误: {str(e)[:50]}")
    
    def _test_connection(self):
        self._save_to_provider()
        
        valid, msg = self.provider_service.validate_provider(self.provider)
        if not valid:
            self.test_status.setText(f"❌ {msg}")
            self.test_status.setStyleSheet("color: #ef4444;")
            return
        
        self.test_status.setText("测试中...")
        self.test_status.setStyleSheet("color: #a1a1aa;")
        
        async def test():
            return await self.provider_service.test_connection(self.provider)
        
        try:
            loop = asyncio.new_event_loop()
            success, message = loop.run_until_complete(test())
            loop.close()
            
            if success:
                self.test_status.setText("✅ 连接成功")
                self.test_status.setStyleSheet("color: #22c55e;")
            else:
                self.test_status.setText(f"❌ {message}")
                self.test_status.setStyleSheet("color: #ef4444;")
        except Exception as e:
            self.test_status.setText(f"❌ {str(e)[:30]}")
            self.test_status.setStyleSheet("color: #ef4444;")
    
    def _save_to_provider(self):
        self.provider.name = self.name_input.text().strip()
        self.provider.api_base = self.api_base_input.text().strip()
        self.provider.api_key = self.api_key_input.text().strip()
        self.provider.default_model = self.model_combo.currentText().strip()
        self.provider.max_tokens = self.max_tokens_input.value()
        self.provider.temperature = self.temperature_input.value()
        self.provider.supports_vision = self.supports_vision_check.isChecked()
        self.provider.supports_thinking = self.supports_thinking_check.isChecked()
        self.provider.enabled = self.enabled_check.isChecked()
        
        headers = {}
        for row in range(self.headers_table.rowCount()):
            key_item = self.headers_table.item(row, 0)
            value_item = self.headers_table.item(row, 1)
            if key_item and value_item:
                key = key_item.text().strip()
                value = value_item.text().strip()
                if key:
                    headers[key] = value
        self.provider.custom_headers = headers
        
        format_text = self.request_format_input.toPlainText().strip()
        if format_text:
            try:
                import json
                self.provider.request_format = json.loads(format_text)
            except:
                self.provider.request_format = {}
        else:
            self.provider.request_format = {}
    
    def _save(self):
        self._save_to_provider()
        
        valid, msg = self.provider_service.validate_provider(self.provider)
        if not valid:
            QMessageBox.warning(self, "验证错误", msg)
            return
        
        self.accept()
    
    def get_provider(self) -> Provider:
        return self.provider
