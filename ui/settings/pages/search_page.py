from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QGroupBox,
    QVBoxLayout as QVBox,
    QFormLayout,
    QCheckBox,
    QComboBox,
    QLineEdit,
)

from models.search_config import SearchConfig


class SearchPage(QWidget):
    page_emoji = "🔍"
    page_title = "网络搜索"

    def __init__(self, search_config: SearchConfig, parent=None):
        super().__init__(parent)
        self._setup_ui(search_config)

    def _setup_ui(self, search_config: SearchConfig) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        enable_group = QGroupBox("搜索服务")
        enable_layout = QVBox(enable_group)

        self.search_enabled_check = QCheckBox("启用网络搜索")
        self.search_enabled_check.setChecked(bool(search_config.enabled))
        self.search_enabled_check.setToolTip("允许模型在需要时搜索互联网获取最新信息")
        enable_layout.addWidget(self.search_enabled_check)

        layout.addWidget(enable_group)

        provider_group = QGroupBox("搜索引擎")
        provider_layout = QFormLayout(provider_group)

        self.search_provider_combo = QComboBox()
        self.search_provider_combo.addItems(["Tavily AI", "Google (SerpAPI)", "SearXNG (自托管)"])
        providers_map = {"tavily": 0, "google": 1, "searxng": 2}
        self.search_provider_combo.setCurrentIndex(providers_map.get(search_config.provider, 0))
        provider_layout.addRow("搜索引擎:", self.search_provider_combo)

        self.search_api_key_edit = QLineEdit()
        self.search_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.search_api_key_edit.setText(search_config.api_key)
        self.search_api_key_edit.setPlaceholderText("API Key (Tavily/SerpAPI)")
        provider_layout.addRow("API Key:", self.search_api_key_edit)

        self.search_api_base_edit = QLineEdit()
        self.search_api_base_edit.setText(search_config.api_base)
        self.search_api_base_edit.setPlaceholderText("http://localhost:8888 (仅 SearXNG)")
        provider_layout.addRow("API 地址:", self.search_api_base_edit)

        layout.addWidget(provider_group)

        options_group = QGroupBox("搜索选项")
        options_layout = QFormLayout(options_group)

        self.search_max_results = QComboBox()
        self.search_max_results.addItems(["3", "5", "10", "20"])
        cur = str(getattr(search_config, "max_results", 5))
        idx = ["3", "5", "10", "20"].index(cur) if cur in ["3", "5", "10", "20"] else 1
        self.search_max_results.setCurrentIndex(idx)
        options_layout.addRow("结果数量:", self.search_max_results)

        self.search_include_date = QCheckBox("结果包含日期")
        self.search_include_date.setChecked(bool(search_config.include_date))
        options_layout.addRow("", self.search_include_date)

        layout.addWidget(options_group)
        layout.addStretch()

    def collect(self) -> SearchConfig:
        providers_map = {0: "tavily", 1: "google", 2: "searxng"}
        return SearchConfig(
            enabled=self.search_enabled_check.isChecked(),
            provider=providers_map.get(self.search_provider_combo.currentIndex(), "tavily"),
            api_key=self.search_api_key_edit.text().strip(),
            api_base=self.search_api_base_edit.text().strip(),
            max_results=int(self.search_max_results.currentText()),
            include_date=self.search_include_date.isChecked(),
        )
