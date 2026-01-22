"""
Message widget for displaying individual messages - Responsive layout
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QToolButton, QTextBrowser, QAbstractScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QPixmap, QTextOption, QGuiApplication
import math

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
        
        self.content_widget = MarkdownView(self.thinking_content)
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

        def _shorten(text: str, max_len: int = 22) -> str:
            if not text:
                return ""
            return text if len(text) <= max_len else (text[: max_len - 1] + "…")

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

        # Model + timestamp (from metadata / created_at)
        model = None
        if isinstance(self.message.metadata, dict):
            model = self.message.metadata.get('model') or self.message.metadata.get('model_name')
        if model:
            model_label = QLabel(_shorten(str(model)))
            model_label.setObjectName("message_badge")
            model_label.setToolTip(str(model))
            header.addWidget(model_label)

        try:
            ts = self.message.created_at.strftime('%m-%d %H:%M')
        except Exception:
            ts = ""
        if ts:
            ts_label = QLabel(ts)
            ts_label.setObjectName("message_badge")
            header.addWidget(ts_label)
        
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

        copy_btn = QToolButton()
        copy_btn.setText("⧉")
        copy_btn.setToolTip("复制原文")
        copy_btn.setFixedSize(26, 22)
        copy_btn.setObjectName("msg_copy_btn")
        copy_btn.clicked.connect(self._copy_original_content)
        self._copy_btn = copy_btn
        header.addWidget(copy_btn)
        
        # Compact action buttons (icon-only)
        edit_btn = QToolButton()
        edit_btn.setText("🖊")
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
        content_view = MarkdownView(content_text)
        content_view.setObjectName("message_content")
        content_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(content_view)
        
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

    def _copy_original_content(self) -> None:
        text = self.message.content
        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)

        try:
            QGuiApplication.clipboard().setText(text)
        except Exception:
            return

        try:
            if hasattr(self, "_copy_btn") and self._copy_btn:
                self._copy_btn.setToolTip("已复制")
                QTimer.singleShot(1200, lambda: self._copy_btn.setToolTip("复制原文"))
        except Exception:
            pass
        


    def _open_image_preview(self, image_data: str):
        dialog = ImageViewerDialog(image_data, self)
        dialog.exec()


class MarkdownView(QTextBrowser):
    """A compact, auto-height markdown-capable viewer.

    Rationale:
    - QLabel wordWrap won't break very long runs (JSON/base64/stream chunks).
    - QTextBrowser can wrap anywhere and render Markdown via QTextDocument.
    - Auto height avoids nested scrollbars inside message bubbles.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenExternalLinks(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

        doc = self.document()
        opt = doc.defaultTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(opt)
        doc.setDocumentMargin(0)

        try:
            doc.documentLayout().documentSizeChanged.connect(lambda *_: self._schedule_update_height())
        except Exception:
            pass

        self.set_markdown(text)

    def set_markdown(self, text: str) -> None:
        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)

        try:
            self.document().setMarkdown(text)
        except Exception:
            self.setPlainText(text)
        self._schedule_update_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_update_height()

    def _schedule_update_height(self) -> None:
        # Defer to next event loop so QTextDocument finishes layout.
        QTimer.singleShot(0, self._update_height)

    def _update_height(self, *_args) -> None:
        try:
            # Ensure the document is laid out to the current viewport width.
            w = max(1, self.viewport().width())
            self.document().setTextWidth(w)

            size = self.document().documentLayout().documentSize()
            h = int(math.ceil(size.height()))
        except Exception:
            h = 0

        # Extra padding avoids clipping on some fonts/styles (dark theme was affected).
        target = max(18, h + 12)
        if self.height() != target:
            self.setFixedHeight(target)
