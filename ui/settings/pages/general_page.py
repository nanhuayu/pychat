from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QFormLayout, QLineEdit, QLabel, QDoubleSpinBox


class GeneralPage(QWidget):
    page_emoji = "⚙️"
    page_title = "常规设置"

    def __init__(self, *, proxy_url: str = "", llm_timeout_seconds: float = 600.0, parent=None):
        super().__init__(parent)
        self._setup_ui(proxy_url, llm_timeout_seconds)

    def _setup_ui(self, proxy_url: str, llm_timeout_seconds: float) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        net_group = QGroupBox("网络")
        net_layout = QFormLayout(net_group)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setText(proxy_url or "")
        self.proxy_edit.setPlaceholderText("http://127.0.0.1:7890")
        net_layout.addRow("代理服务器:", self.proxy_edit)

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(30.0, 3600.0)
        self.timeout_spin.setDecimals(0)
        self.timeout_spin.setSingleStep(30.0)
        self.timeout_spin.setValue(float(llm_timeout_seconds or 600.0))
        self.timeout_spin.setToolTip("模型请求的总超时。流式响应、首包等待和长输出都受此值影响。")
        net_layout.addRow("模型超时(秒):", self.timeout_spin)
        layout.addWidget(net_group)

        hint = QLabel("代理仅在你需要通过本地代理访问模型服务时使用；留空表示直连。模型超时建议按服务端稳定性设置，默认 600 秒。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()

    def collect(self) -> dict:
        return {
            "proxy_url": (self.proxy_edit.text() or "").strip(),
            "llm_timeout_seconds": float(self.timeout_spin.value()),
        }
