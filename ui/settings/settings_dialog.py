"""
Settings dialog - unified all setting pages in one file for simplicity
"""
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QStackedWidget,
    QPushButton, QLabel, QFrame, QGroupBox, QComboBox,
    QCheckBox, QLineEdit, QMessageBox, QToolButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRect
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QFont
from typing import List

from models.provider import Provider
from models.search_config import SearchConfig
from services.provider_service import ProviderService
from services.storage_service import StorageService
from ui.dialogs.provider_dialog import ProviderDialog
from ui.dialogs.mcp_server_dialog import McpSettingsWidget


def create_emoji_icon(emoji: str, size: int =20) -> QIcon:
    """将 Emoji 渲染为等宽图标，确保对齐"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    # Windows 上使用 Segoe UI Emoji 效果最好
    font = QFont("Segoe UI Emoji", size - 8)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignLeft, emoji)
    painter.end()
    return QIcon(pixmap)


# ============ Helper: Provider List Item ============
class ProviderListItem(QListWidgetItem):
    def __init__(self, provider: Provider):
        super().__init__()
        self.provider = provider
        self.update_display()
    
    def update_display(self):
        status = "✅" if self.provider.enabled else "⚪"
        self.setText(f"{status}  {self.provider.name}")
        self.setToolTip(f"API: {self.provider.api_base}\n模型数: {len(self.provider.models)}")


# ============ Main Dialog ============
class SettingsDialog(QDialog):
    providers_changed = pyqtSignal()

    def __init__(self, providers: List[Provider], current_settings: dict | None = None, parent=None):
        super().__init__(parent)
        self.providers = providers
        self.current_settings = current_settings or {}
        self.provider_service = ProviderService()
        self.storage = StorageService()
        self.search_config = self.storage.load_search_config()
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("设置")
        self.setObjectName("settings_dialog")
        self.setMinimumSize(750, 550)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # === Sidebar ===
        sidebar = QFrame()
        sidebar.setObjectName("settings_sidebar")
        sidebar.setFixedWidth(180)
        
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 16, 8, 16)
        sidebar_layout.setSpacing(4)
        
        self.page_list = QListWidget()
        self.page_list.setObjectName("settings_nav")
        self.page_list.setIconSize(QSize(20, 20))
        # 确保列表占据所有可用空间
        self.page_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        pages = [
            ("🤖", "模型服务"),
            ("🔌", "MCP 服务器"),
            ("🔍", "网络搜索"),
            ("🎨", "外观设置"),
            ("⚙️", "常规设置"),
        ]
        
        for emoji, title in pages:
            item = QListWidgetItem(f" {title}")
            item.setIcon(create_emoji_icon(emoji))
            self.page_list.addItem(item)
        
        self.page_list.currentRowChanged.connect(self._change_page)
        sidebar_layout.addWidget(self.page_list, 1)  # 设置伸缩因子为 1
        
        # 移除了 sidebar_layout.addStretch()，因为 page_list 已经占满了
        
        # Buttons
        sidebar_layout.addSpacing(10) # 稍微留一点间距
        save_btn = QPushButton("保存")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self.accept)
        sidebar_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        sidebar_layout.addWidget(cancel_btn)
        
        layout.addWidget(sidebar)

        # === Content Area ===
        self.content = QStackedWidget()
        self.content.setObjectName("settings_content")
        layout.addWidget(self.content)

        self._init_pages()
        self.page_list.setCurrentRow(0)

    def _init_pages(self):
        # Page 0: Models
        self.content.addWidget(self._create_models_page())
        # Page 1: MCP
        self.content.addWidget(self._create_mcp_page())
        # Page 2: Search
        self.content.addWidget(self._create_search_page())
        # Page 3: Appearance
        self.content.addWidget(self._create_appearance_page())
        # Page 4: General
        self.content.addWidget(self._create_general_page())

    def _change_page(self, index):
        self.content.setCurrentIndex(index)

    # ============ Page 0: Models ============
    def _create_models_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("模型服务商"))
        header.addStretch()
        
        btn_add = QToolButton()
        btn_add.setObjectName("toolbar_btn")
        btn_add.setText("➕")
        btn_add.setToolTip("添加服务商")
        btn_add.clicked.connect(self._add_provider)
        header.addWidget(btn_add)
        
        btn_default = QToolButton()
        btn_default.setObjectName("toolbar_btn")
        btn_default.setText("📥")
        btn_default.setToolTip("导入默认配置")
        btn_default.clicked.connect(self._add_default_providers)
        header.addWidget(btn_default)
        
        layout.addLayout(header)

        # List
        self.provider_list = QListWidget()
        self.provider_list.setObjectName("settings_list")
        self.provider_list.itemDoubleClicked.connect(self._edit_provider)
        self._refresh_provider_list()
        layout.addWidget(self.provider_list)

        # Actions
        actions = QHBoxLayout()
        actions.setSpacing(6)
        
        for text, icon, slot in [
            ("编辑", "📝", self._edit_provider),
            ("上移", "⬆", lambda: self._move_provider(-1)),
            ("下移", "⬇", lambda: self._move_provider(1)),
        ]:
            btn = QPushButton(f"{icon} {text}")
            btn.clicked.connect(slot)
            actions.addWidget(btn)
        
        btn_del = QPushButton("🗑 删除")
        btn_del.setProperty("danger", True)
        btn_del.clicked.connect(self._delete_provider)
        actions.addWidget(btn_del)
        
        layout.addLayout(actions)
        layout.addWidget(QLabel("提示: 双击列表项可快速编辑"))
        return page

    def _refresh_provider_list(self):
        self.provider_list.clear()
        for p in self.providers:
            self.provider_list.addItem(ProviderListItem(p))

    def _add_provider(self):
        dialog = ProviderDialog(parent=self)
        if dialog.exec():
            self.providers.append(dialog.get_provider())
            self._refresh_provider_list()
            self.providers_changed.emit()

    def _edit_provider(self):
        item = self.provider_list.currentItem()
        if not isinstance(item, ProviderListItem):
            return
        dialog = ProviderDialog(item.provider, self)
        if dialog.exec():
            item.update_display()
            self.providers_changed.emit()

    def _delete_provider(self):
        item = self.provider_list.currentItem()
        if not isinstance(item, ProviderListItem):
            QMessageBox.information(self, "提示", "请先选择一个服务商")
            return
        if QMessageBox.question(self, '删除', f'确定删除 "{item.provider.name}"？') == QMessageBox.StandardButton.Yes:
            self.providers.remove(item.provider)
            self._refresh_provider_list()
            self.providers_changed.emit()

    def _move_provider(self, delta):
        row = self.provider_list.currentRow()
        if row < 0: return
        new_row = row + delta
        if 0 <= new_row < len(self.providers):
            self.providers[row], self.providers[new_row] = self.providers[new_row], self.providers[row]
            self._refresh_provider_list()
            self.provider_list.setCurrentRow(new_row)
            self.providers_changed.emit()

    def _add_default_providers(self):
        defaults = self.provider_service.create_default_providers()
        existing = {p.name for p in self.providers}
        added = sum(1 for p in defaults if p.name not in existing and (self.providers.append(p) or True))
        if added:
            self._refresh_provider_list()
            self.providers_changed.emit()
            QMessageBox.information(self, "成功", f"已添加 {added} 个默认服务商")
        else:
            QMessageBox.information(self, "提示", "所有默认服务商已存在")

    # ============ Page 1: MCP ============
    def _create_mcp_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(QLabel("MCP 服务器配置"))
        layout.addWidget(McpSettingsWidget())
        hint = QLabel(
            "提示：启用 MCP 后，应用会自动提供内置工具（builtin_filesystem_ls/read/grep、builtin_python_exec），\n"
            "无需额外安装服务器；也可在上方添加外部 MCP Server 以扩展更多工具。"
        )
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    # ============ Page 2: Search ============
    def _create_search_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Enable
        enable_group = QGroupBox("搜索服务")
        enable_layout = QVBoxLayout(enable_group)
        
        self.search_enabled_check = QCheckBox("启用网络搜索")
        self.search_enabled_check.setChecked(self.search_config.enabled)
        self.search_enabled_check.setToolTip("允许模型在需要时搜索互联网获取最新信息")
        enable_layout.addWidget(self.search_enabled_check)
        
        layout.addWidget(enable_group)

        # Provider
        provider_group = QGroupBox("搜索引擎")
        provider_layout = QFormLayout(provider_group)
        
        self.search_provider_combo = QComboBox()
        self.search_provider_combo.addItems(["Tavily AI", "Google (SerpAPI)", "SearXNG (自托管)"])
        providers_map = {"tavily": 0, "google": 1, "searxng": 2}
        self.search_provider_combo.setCurrentIndex(providers_map.get(self.search_config.provider, 0))
        provider_layout.addRow("搜索引擎:", self.search_provider_combo)
        
        self.search_api_key_edit = QLineEdit()
        self.search_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.search_api_key_edit.setText(self.search_config.api_key)
        self.search_api_key_edit.setPlaceholderText("API Key (Tavily/SerpAPI)")
        provider_layout.addRow("API Key:", self.search_api_key_edit)
        
        self.search_api_base_edit = QLineEdit()
        self.search_api_base_edit.setText(self.search_config.api_base)
        self.search_api_base_edit.setPlaceholderText("http://localhost:8888 (仅 SearXNG)")
        provider_layout.addRow("API 地址:", self.search_api_base_edit)
        
        layout.addWidget(provider_group)

        # Options
        options_group = QGroupBox("搜索选项")
        options_layout = QFormLayout(options_group)
        
        self.search_max_results = QComboBox()
        self.search_max_results.addItems(["3", "5", "10", "20"])
        idx = ["3", "5", "10", "20"].index(str(self.search_config.max_results)) if str(self.search_config.max_results) in ["3", "5", "10", "20"] else 1
        self.search_max_results.setCurrentIndex(idx)
        options_layout.addRow("结果数量:", self.search_max_results)
        
        self.search_include_date = QCheckBox("结果包含日期")
        self.search_include_date.setChecked(self.search_config.include_date)
        options_layout.addRow("", self.search_include_date)
        
        layout.addWidget(options_group)
        layout.addStretch()
        return page

    def _get_search_config(self) -> SearchConfig:
        """Build SearchConfig from UI"""
        providers_map = {0: "tavily", 1: "google", 2: "searxng"}
        return SearchConfig(
            enabled=self.search_enabled_check.isChecked(),
            provider=providers_map.get(self.search_provider_combo.currentIndex(), "tavily"),
            api_key=self.search_api_key_edit.text().strip(),
            api_base=self.search_api_base_edit.text().strip(),
            max_results=int(self.search_max_results.currentText()),
            include_date=self.search_include_date.isChecked(),
        )

    # ============ Page 3: Appearance ============
    def _create_appearance_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Theme
        theme_group = QGroupBox("主题")
        theme_layout = QFormLayout(theme_group)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["深色", "浅色"])
        theme = (self.current_settings.get('theme') or 'dark').lower()
        self.theme_combo.setCurrentIndex(1 if theme == 'light' else 0)
        theme_layout.addRow("界面主题:", self.theme_combo)
        layout.addWidget(theme_group)

        # Display
        display_group = QGroupBox("显示")
        display_layout = QVBoxLayout(display_group)
        
        self.stats_check = QCheckBox("显示统计面板")
        self.stats_check.setChecked(bool(self.current_settings.get('show_stats', True)))
        display_layout.addWidget(self.stats_check)
        
        self.thinking_check = QCheckBox("显示思考过程")
        self.thinking_check.setChecked(bool(self.current_settings.get('show_thinking', True)))
        display_layout.addWidget(self.thinking_check)
        
        self.log_check = QCheckBox("记录流式日志 (Debug)")
        self.log_check.setChecked(bool(self.current_settings.get('log_stream', False)))
        display_layout.addWidget(self.log_check)
        
        layout.addWidget(display_group)
        layout.addStretch()
        return page

    # ============ Page 3: General ============
    def _create_general_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Network
        net_group = QGroupBox("网络")
        net_layout = QFormLayout(net_group)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setText(self.current_settings.get('proxy_url', ''))
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:7890")
        net_layout.addRow("代理服务器:", self.proxy_edit)
        layout.addWidget(net_group)

        # About
        about_group = QGroupBox("关于")
        about_layout = QVBoxLayout(about_group)
        about_layout.addWidget(QLabel("PyChat v0.5.0"))
        about_layout.addWidget(QLabel("基于 PyQt6 + MCP 构建"))
        layout.addWidget(about_group)
        
        layout.addStretch()
        return page

    # ============ Getters for MainWindow ============
    def get_providers(self) -> List[Provider]:
        return self.providers

    def get_show_stats(self) -> bool:
        return self.stats_check.isChecked()

    def get_theme(self) -> str:
        return 'light' if self.theme_combo.currentIndex() == 1 else 'dark'

    def get_show_thinking(self) -> bool:
        return self.thinking_check.isChecked()

    def get_log_stream(self) -> bool:
        return self.log_check.isChecked()
    
    def get_proxy_url(self) -> str:
        return self.proxy_edit.text().strip()

    def accept(self):
        """Save all settings before closing"""
        # Save search config
        self.storage.save_search_config(self._get_search_config())
        super().accept()
