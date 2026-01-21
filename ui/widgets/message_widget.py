"""
Message widget for displaying individual messages - Responsive layout
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QToolButton
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPixmap

from models.conversation import Message
from ui.dialogs.image_viewer import ImageViewerDialog
from ui.utils.image_loader import load_pixmap


class ImageThumbnail(QLabel):
    """Clickable image thumbnail"""
    
    clicked = pyqtSignal()
    
    def __init__(self, image_data: str, parent=None):
        super().__init__(parent)
        self.setObjectName("image_thumbnail")
        self.setFixedSize(80, 80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_image(image_data)
    
    def _load_image(self, image_data: str):
        try:
            pixmap = load_pixmap(image_data)
            
            if not pixmap.isNull():
                scaled = pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                self.setPixmap(scaled)
                self.setProperty("state", "image")
                self.setText("")
            else:
                self.setProperty("state", "placeholder")
                self.setText("IMG")
                self.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.style().unpolish(self)
            self.style().polish(self)
        except Exception:
            self.setProperty("state", "error")
            self.setText("⚠️")
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.style().unpolish(self)
            self.style().polish(self)
    
    def mousePressEvent(self, event):
        self.clicked.emit()


class ThinkingSection(QWidget):
    """Collapsible thinking section"""
    
    def __init__(self, thinking_content: str, parent=None):
        super().__init__(parent)
        self.thinking_content = thinking_content
        self.is_expanded = False
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(2)
        
        self.toggle_btn = QPushButton("思考")
        self.toggle_btn.setObjectName("thinking_toggle")
        self.toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self.toggle_btn)
        
        self.content_widget = QLabel(self.thinking_content)
        self.content_widget.setWordWrap(True)
        self.content_widget.setObjectName("thinking_content")
        self.content_widget.setVisible(False)
        layout.addWidget(self.content_widget)
    
    def _toggle(self):
        self.is_expanded = not self.is_expanded
        self.content_widget.setVisible(self.is_expanded)
        self.toggle_btn.setText("收起思考" if self.is_expanded else "思考")


class MessageWidget(QFrame):
    """Widget for displaying a single message - Compact responsive layout"""
    
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    
    def __init__(self, message: Message, parent=None):
        super().__init__(parent)
        self.message = message
        self._setup_ui()
    
    def _setup_ui(self):
        is_user = self.message.role == 'user'

        # Themeable styling via QSS
        self.setObjectName("message_widget")
        self.setProperty("role", "user" if is_user else "assistant")
        
        # Use size policy for responsive layout
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        
        # Header - compact
        header = QHBoxLayout()
        header.setSpacing(8)
        
        role_label = QLabel("你" if is_user else "助手")
        role_label.setObjectName("message_role")
        header.addWidget(role_label)
        
        # Stats - compact badges
        if self.message.tokens:
            token_label = QLabel(f"T:{self.message.tokens}")
            token_label.setObjectName("message_badge")
            header.addWidget(token_label)
        
        if self.message.response_time_ms:
            time_label = QLabel(f"{self.message.response_time_ms / 1000:.1f}s")
            time_label.setObjectName("message_badge")
            header.addWidget(time_label)
        
        header.addStretch()
        
        # Compact action buttons (icon-only)
        edit_btn = QToolButton()
        edit_btn.setText("✎")
        edit_btn.setToolTip("编辑")
        edit_btn.setFixedSize(26, 22)
        edit_btn.setObjectName("msg_edit_btn")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.message.id))
        header.addWidget(edit_btn)

        delete_btn = QToolButton()
        delete_btn.setText("✕")
        delete_btn.setToolTip("删除")
        delete_btn.setFixedSize(26, 22)
        delete_btn.setObjectName("msg_delete_btn")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.message.id))
        header.addWidget(delete_btn)
        
        layout.addLayout(header)

        # Thinking (assistant only) - show above final content
        if (not is_user) and self.message.thinking:
            layout.addWidget(ThinkingSection(self.message.thinking))
        
        # Content
        content_text = self.message.content
        if not isinstance(content_text, str):
            content_text = str(content_text)
        content_label = QLabel(content_text)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_label.setObjectName("message_content")
        content_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(content_label)
        
        # Images
        if self.message.images:
            images_layout = QHBoxLayout()
            images_layout.setSpacing(4)
            for image_data in self.message.images[:4]:
                thumb = ImageThumbnail(image_data)
                thumb.clicked.connect(lambda _=None, d=image_data: self._open_image_preview(d))
                images_layout.addWidget(thumb)
            images_layout.addStretch()
            layout.addLayout(images_layout)
        


    def _open_image_preview(self, image_data: str):
        dialog = ImageViewerDialog(image_data, self)
        dialog.exec()
