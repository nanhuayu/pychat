from __future__ import annotations

from typing import List

from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QToolButton,
    QMessageBox,
)

from models.provider import Provider
from services.provider_service import ProviderService
from ui.dialogs.provider_dialog import ProviderDialog


class ProviderListItem(QListWidgetItem):
    def __init__(self, provider: Provider):
        super().__init__()
        self.provider = provider
        self.update_display()

    def update_display(self) -> None:
        status = "✅" if getattr(self.provider, "enabled", True) else "⚪"
        self.setText(f"{status}  {self.provider.name}")
        self.setToolTip(f"API: {self.provider.api_base}\n模型数: {len(self.provider.models)}")


class ModelsPage(QWidget):
    providers_changed = pyqtSignal()

    page_emoji = "🤖"
    page_title = "模型服务商"

    def __init__(self, providers: List[Provider], provider_service: ProviderService | None = None, parent=None):
        super().__init__(parent)
        self.providers: List[Provider] = list(providers or [])
        self.provider_service = provider_service or ProviderService()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(QLabel(self.page_title))
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

        self.provider_list = QListWidget()
        self.provider_list.setObjectName("settings_list")
        self.provider_list.itemDoubleClicked.connect(lambda _item: self._edit_provider())
        layout.addWidget(self.provider_list)

        actions = QHBoxLayout()
        actions.setSpacing(6)

        btn_edit = QPushButton("📝 编辑")
        btn_edit.clicked.connect(self._edit_provider)
        actions.addWidget(btn_edit)

        btn_up = QPushButton("⬆ 上移")
        btn_up.clicked.connect(lambda: self._move_provider(-1))
        actions.addWidget(btn_up)

        btn_down = QPushButton("⬇ 下移")
        btn_down.clicked.connect(lambda: self._move_provider(1))
        actions.addWidget(btn_down)

        btn_del = QPushButton("🗑 删除")
        btn_del.setProperty("danger", True)
        btn_del.clicked.connect(self._delete_provider)
        actions.addWidget(btn_del)

        actions.addStretch()
        layout.addLayout(actions)

        layout.addWidget(QLabel("提示: 双击列表项可快速编辑"))
        layout.addStretch()

        self._refresh_provider_list()

    def _refresh_provider_list(self) -> None:
        self.provider_list.clear()
        for p in self.providers:
            self.provider_list.addItem(ProviderListItem(p))

    def _add_provider(self) -> None:
        dialog = ProviderDialog(parent=self)
        if dialog.exec():
            p = dialog.get_provider()
            self.providers.append(p)
            self._refresh_provider_list()
            self.providers_changed.emit()

    def _edit_provider(self) -> None:
        item = self.provider_list.currentItem()
        if not isinstance(item, ProviderListItem):
            return
        dialog = ProviderDialog(item.provider, self)
        if dialog.exec():
            updated = dialog.get_provider()
            try:
                idx = self.providers.index(item.provider)
                self.providers[idx] = updated
            except Exception:
                # Fallback: match by id
                for i, p in enumerate(self.providers):
                    if getattr(p, "id", None) == getattr(updated, "id", None):
                        self.providers[i] = updated
                        break
            self._refresh_provider_list()
            self.providers_changed.emit()

    def _delete_provider(self) -> None:
        item = self.provider_list.currentItem()
        if not isinstance(item, ProviderListItem):
            return
        if QMessageBox.question(self, "删除", f'确定删除 "{item.provider.name}"？') == QMessageBox.StandardButton.Yes:
            try:
                self.providers.remove(item.provider)
            except Exception:
                self.providers = [p for p in self.providers if getattr(p, "id", None) != getattr(item.provider, "id", None)]
            self._refresh_provider_list()
            self.providers_changed.emit()

    def _move_provider(self, delta: int) -> None:
        row = self.provider_list.currentRow()
        if row < 0:
            return
        new_row = row + int(delta)
        if 0 <= new_row < len(self.providers):
            self.providers[row], self.providers[new_row] = self.providers[new_row], self.providers[row]
            self._refresh_provider_list()
            self.provider_list.setCurrentRow(new_row)
            self.providers_changed.emit()

    def _add_default_providers(self) -> None:
        defaults = self.provider_service.create_default_providers()
        existing = {p.name for p in self.providers}
        added_any = False
        for p in defaults:
            if p.name in existing:
                continue
            self.providers.append(p)
            added_any = True

        if added_any:
            self._refresh_provider_list()
            self.providers_changed.emit()

    def get_providers(self) -> List[Provider]:
        return list(self.providers)
