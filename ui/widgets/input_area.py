"""
Input area widget - Compact responsive layout
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTextEdit, QLabel, QFileDialog, QComboBox,
    QFrame, QSizePolicy, QToolButton
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QKeyEvent, QDragEnterEvent, QDropEvent, QPixmap
import base64
import os
from typing import List


class ImagePreviewItem(QFrame):
    """Preview item for attached images"""
    
    remove_requested = pyqtSignal(str)
    
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self._setup_ui()
    
    def _setup_ui(self):
        self.setObjectName("image_preview_item")
        self.setFixedSize(48, 48)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)
        
        thumb = QLabel()
        thumb.setObjectName("image_thumb")
        pixmap = QPixmap(self.image_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(38, 30, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            thumb.setPixmap(scaled)
        else:
            thumb.setText("IMG")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(thumb)
        
        remove_btn = QPushButton("×")
        remove_btn.setObjectName("image_remove_btn")
        remove_btn.setFixedSize(12, 12)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.image_path))
        layout.addWidget(remove_btn, alignment=Qt.AlignmentFlag.AlignRight)


class MessageTextEdit(QTextEdit):
    """Custom text edit with Ctrl+Enter to send"""
    
    send_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
    
    def keyPressEvent(self, event: QKeyEvent):
        if (event.key() == Qt.Key.Key_Return and 
            event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self.send_requested.emit()
        else:
            super().keyPressEvent(event)


class InputArea(QWidget):
    """Input area - single-row compact toolbar + input"""
    
    message_sent = pyqtSignal(str, list)
    conversation_settings_requested = pyqtSignal()
    provider_settings_requested = pyqtSignal()  # New: quick access to provider config
    show_thinking_changed = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("input_container")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._attached_images: List[str] = []
        self._providers = []
        self._suppress_thinking_signal = False
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(3)
        
        # Image preview (hidden by default)
        self.image_preview = QWidget()
        self.image_preview.setObjectName("image_preview")
        self.image_layout = QHBoxLayout(self.image_preview)
        self.image_layout.setContentsMargins(4, 0, 4, 0)
        self.image_layout.setSpacing(4)
        self.image_layout.addStretch()
        self.image_preview.setVisible(False)
        layout.addWidget(self.image_preview)
        
        # ===== Main input wrapper =====
        input_wrapper = QFrame()
        input_wrapper.setObjectName("input_wrapper")
        
        wrapper_layout = QVBoxLayout(input_wrapper)
        wrapper_layout.setContentsMargins(6, 6, 6, 6)
        wrapper_layout.setSpacing(4)
        
        # Text input
        self.text_input = MessageTextEdit()
        self.text_input.setObjectName("message_input")
        self.text_input.setPlaceholderText("输入消息... (Ctrl+Enter 发送)")
        self.text_input.setMinimumHeight(40)
        self.text_input.setMaximumHeight(120)
        self.text_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text_input.send_requested.connect(self._send_message)
        wrapper_layout.addWidget(self.text_input)
        
        # ===== Single-row toolbar: [📎] [Provider▾] [Model▾] [🧠] [⚙] [🔧] --- [发送] =====
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        
        # Attach button
        self.attach_btn = QToolButton()
        self.attach_btn.setObjectName("toolbar_btn")
        self.attach_btn.setText("📎")
        self.attach_btn.setToolTip("添加图片")
        self.attach_btn.clicked.connect(self._attach_image)
        toolbar.addWidget(self.attach_btn)
        
        # Provider selector
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("provider_combo")
        self.provider_combo.setMinimumWidth(70)
        self.provider_combo.setMaximumWidth(110)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        toolbar.addWidget(self.provider_combo)
        
        # Model selector
        self.model_combo = QComboBox()
        self.model_combo.setObjectName("model_combo")
        self.model_combo.setMinimumWidth(120)
        self.model_combo.setMaximumWidth(200)
        self.model_combo.setEditable(True)
        toolbar.addWidget(self.model_combo)
        
        # Thinking toggle
        self.thinking_toggle = QToolButton()
        self.thinking_toggle.setObjectName("toolbar_btn")
        self.thinking_toggle.setText("🧠")
        self.thinking_toggle.setToolTip("显示思考过程")
        self.thinking_toggle.setCheckable(True)
        self.thinking_toggle.toggled.connect(self._on_thinking_toggled)
        toolbar.addWidget(self.thinking_toggle)
        
        # Conversation settings
        self.conv_settings_btn = QToolButton()
        self.conv_settings_btn.setObjectName("toolbar_btn")
        self.conv_settings_btn.setText("⚙")
        self.conv_settings_btn.setToolTip("对话设置 (采样参数/系统提示)")
        self.conv_settings_btn.clicked.connect(self.conversation_settings_requested.emit)
        toolbar.addWidget(self.conv_settings_btn)
        
        # Provider settings (quick access)
        self.provider_settings_btn = QToolButton()
        self.provider_settings_btn.setObjectName("toolbar_btn")
        self.provider_settings_btn.setText("🔧")
        self.provider_settings_btn.setToolTip("配置服务商 (API/Key/模型列表)")
        self.provider_settings_btn.clicked.connect(self.provider_settings_requested.emit)
        toolbar.addWidget(self.provider_settings_btn)
        
        toolbar.addStretch()
        
        # Send button
        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("send_btn")
        self.send_btn.setFixedHeight(26)
        self.send_btn.clicked.connect(self._send_message)
        toolbar.addWidget(self.send_btn)
        
        wrapper_layout.addLayout(toolbar)
        layout.addWidget(input_wrapper)

    
    def set_providers(self, providers: list):
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        self._providers = providers
        
        for provider in providers:
            self.provider_combo.addItem(provider.name, provider.id)
        
        self.provider_combo.blockSignals(False)
        if providers:
            self._on_provider_changed(0)
    
    def _on_provider_changed(self, index: int):
        self.model_combo.clear()
        
        if 0 <= index < len(self._providers):
            provider = self._providers[index]
            for model in provider.models:
                self.model_combo.addItem(model)
            
            if provider.default_model:
                idx = self.model_combo.findText(provider.default_model)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)
                else:
                    self.model_combo.setCurrentText(provider.default_model)
    
    def get_selected_provider_id(self) -> str:
        return self.provider_combo.currentData() or ""
    
    def get_selected_model(self) -> str:
        return self.model_combo.currentText()

    def set_show_thinking(self, enabled: bool):
        self._suppress_thinking_signal = True
        try:
            self.thinking_toggle.setChecked(bool(enabled))
        finally:
            self._suppress_thinking_signal = False

    def _on_thinking_toggled(self, checked: bool):
        if self._suppress_thinking_signal:
            return
        self.show_thinking_changed.emit(bool(checked))
    
    def _attach_image(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, '添加图片', '',
            '图片 (*.png *.jpg *.jpeg *.gif *.webp);;所有文件 (*)'
        )
        for file_path in file_paths:
            self._add_image(file_path)
    
    def _add_image(self, file_path: str):
        if file_path in self._attached_images:
            return
        
        self._attached_images.append(file_path)
        preview = ImagePreviewItem(file_path)
        preview.remove_requested.connect(self._remove_image)
        self.image_layout.insertWidget(self.image_layout.count() - 1, preview)
        self.image_preview.setVisible(True)
    
    def _remove_image(self, image_path: str):
        if image_path in self._attached_images:
            self._attached_images.remove(image_path)
        
        for i in range(self.image_layout.count()):
            item = self.image_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, ImagePreviewItem) and widget.image_path == image_path:
                widget.deleteLater()
                break
        
        if not self._attached_images:
            self.image_preview.setVisible(False)
    
    def _send_message(self):
        content = self.text_input.toPlainText().strip()

        # 允许空输入触发发送：主窗口会根据当前会话状态决定是否忽略。
        # 这用于“导入后只有一条 user 消息，直接基于该会话发送一次”的场景。
        if not content and not self._attached_images:
            self.message_sent.emit("", [])
            return
        
        encoded_images = []
        for image_path in self._attached_images:
            try:
                with open(image_path, 'rb') as f:
                    data = base64.b64encode(f.read()).decode('utf-8')
                    ext = os.path.splitext(image_path)[1].lower()
                    mime = {'.png': 'image/png', '.jpg': 'image/jpeg',
                            '.jpeg': 'image/jpeg', '.gif': 'image/gif',
                            '.webp': 'image/webp'}.get(ext, 'image/png')
                    encoded_images.append(f"data:{mime};base64,{data}")
            except Exception as e:
                print(f"Error: {e}")
        
        self.message_sent.emit(content, encoded_images)
        
        self.text_input.clear()
        self._attached_images.clear()
        while self.image_layout.count() > 1:
            item = self.image_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.image_preview.setVisible(False)
    
    def set_enabled(self, enabled: bool):
        self.text_input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                self._add_image(file_path)
