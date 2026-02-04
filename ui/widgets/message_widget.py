"""
Message widget for displaying individual messages - Responsive layout
"""

import json
import math
from typing import List, Optional, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QToolButton, QTextBrowser, QAbstractScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QSize
from PyQt6.QtGui import QTextOption, QGuiApplication, QCursor

try:
    import markdown
except ImportError:
    markdown = None

from models.conversation import Message
from ui.dialogs.image_viewer import ImageViewerDialog
from ui.utils.image_loader import load_pixmap


MARKDOWN_CSS = """
<style>
    p { margin-bottom: 8px; margin-top: 0; }
    
    /* Headings */
    h1, h2, h3, h4, h5, h6 { 
        margin-top: 16px; margin-bottom: 8px; 
        font-weight: 600; 
    }
    
    /* Code blocks */
    pre { 
        background-color: rgba(128, 128, 128, 0.15); 
        padding: 10px; 
        border-radius: 6px; 
        margin: 8px 0;
    }
    code { 
        background-color: rgba(128, 128, 128, 0.15); 
        padding: 2px 4px; 
        border-radius: 4px;
        font-family: "Consolas", "Monaco", monospace;
    }
    pre code {
        background-color: transparent;
        padding: 0;
        border-radius: 0;
    }
    
    /* Tables */
    table { 
        border-collapse: collapse; 
        width: 100%; 
        margin: 10px 0; 
        border: 1px solid rgba(128, 128, 128, 0.3);
    }
    th { 
        background-color: rgba(128, 128, 128, 0.1); 
        font-weight: 700; 
        padding: 6px; 
        border: 1px solid rgba(128, 128, 128, 0.3);
        text-align: left;
    }
    td { 
        padding: 6px; 
        border: 1px solid rgba(128, 128, 128, 0.3);
    }
    
    /* Blockquotes */
    blockquote { 
        border-left: 4px solid rgba(128, 128, 128, 0.3); 
        padding-left: 10px; 
        margin: 8px 0; 
        color: rgba(128, 128, 128, 0.8);
    }
    
    /* Links */
    a { color: #2962ff; text-decoration: none; }
</style>
"""


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
        except Exception:
            self.setProperty("state", "error")
            self.setText("⚠️")
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        finally:
            self.style().unpolish(self)
            self.style().polish(self)
    
    def mousePressEvent(self, event):
        self.clicked.emit()


class MarkdownView(QTextBrowser):
    """A compact, auto-height markdown-capable viewer."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenExternalLinks(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

        doc = self.document()
        opt = doc.defaultTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(opt)
        doc.setDocumentMargin(0)
        
        # Monitor document size changes
        try:
            doc.documentLayout().documentSizeChanged.connect(self._on_document_size_changed)
        except Exception:
            pass

        self.set_markdown(text)

    def set_markdown(self, text: str) -> None:
        if text is None:
            text = ""
        text = str(text)

        if markdown:
            try:
                extensions = ['fenced_code', 'tables', 'sane_lists']
                html = markdown.markdown(text, extensions=extensions)
                self.setHtml(MARKDOWN_CSS + html)
            except Exception:
                self.document().setMarkdown(text)
        else:
            try:
                self.document().setMarkdown(text)
            except Exception:
                self.setPlainText(text)
        
        # Force update geometry
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Recalculate height on width change
        self.updateGeometry()

    def _on_document_size_changed(self, *_args):
        self.updateGeometry()

    def minimumSizeHint(self):
        return QSize(0, 0)

    def sizeHint(self):
        try:
            # Calculate height based on content
            self.document().setTextWidth(self.viewport().width())
            size = self.document().documentLayout().documentSize()
            h = int(math.ceil(size.height()))
            # Add small padding
            return QSize(self.viewport().width(), max(18, h + 12))
        except Exception:
            return QSize(100, 30)


class ThinkingSection(QWidget):
    """Collapsible thinking section - Concise Style"""
    
    def __init__(self, thinking_content: str, parent=None):
        super().__init__(parent)
        self.thinking_content = thinking_content
        self.is_expanded = False
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)
        
        self.toggle_btn = QToolButton()
        self.toggle_btn.setObjectName("thinking_toggle")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle_btn.setText("💭 思考过程")
        
        self.toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self.toggle_btn)
        
        self.content_widget = MarkdownView(self.thinking_content)
        self.content_widget.setObjectName("thinking_content")
        self.content_widget.setVisible(False)
        layout.addWidget(self.content_widget)
    
    def _toggle(self):
        self.is_expanded = not self.is_expanded
        self.content_widget.setVisible(self.is_expanded)
        self.toggle_btn.setText("💭 思考过程" if not self.is_expanded else "💭 收起思考")


class ToolCallItem(QWidget):
    """Widget for a single tool call with collapsible details - Concise Style"""
    
    def __init__(self, tool_call: dict, parent=None):
        super().__init__(parent)
        self.tool_call = tool_call
        self.tool_id = tool_call.get('id')
        self.is_expanded = False
        self._setup_ui()
        
        # Auto-set result if present in tool_call data
        if 'result' in self.tool_call:
            self.set_result(self.tool_call['result'])
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)
        
        # Header (Toggle button)
        self.toggle_btn = QToolButton()
        self.toggle_btn.setObjectName("tool_call_header")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        func = self.tool_call.get('function', {})
        name = func.get('name', 'unknown_tool')
        
        # Initial state is "Running"
        self.toggle_btn.setText(f"⏳ 正在使用 {name}...")
        self.toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self.toggle_btn)
        
        # Details container (Args + Result)
        self.details_widget = QWidget()
        self.details_widget.setVisible(False)
        
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 4, 0, 4)
        details_layout.setSpacing(8)
        
        # Arguments (Monospace, minimal)
        args_str = func.get('arguments', '{}')
        try:
            args_obj = json.loads(args_str)
            args_display = json.dumps(args_obj, indent=2, ensure_ascii=False)
        except:
            args_display = args_str
            
        args_label = QLabel("输入参数:")
        args_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #888;")
        details_layout.addWidget(args_label)
        
        self.args_view = QTextBrowser()
        self.args_view.setPlainText(args_display)
        self.args_view.setMaximumHeight(120)
        details_layout.addWidget(self.args_view)
        
        # Result section
        self.result_label = QLabel("执行结果:")
        self.result_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #888; margin-top: 4px;")
        self.result_label.setVisible(False)
        details_layout.addWidget(self.result_label)
        
        self.result_view = MarkdownView("")
        self.result_view.setVisible(False)
        details_layout.addWidget(self.result_view)
        
        layout.addWidget(self.details_widget)
        
    def _toggle(self):
        self.is_expanded = not self.is_expanded
        self.details_widget.setVisible(self.is_expanded)
        
    def set_result(self, result: str):
        self.result_label.setVisible(True)
        self.result_view.setVisible(True)
        self.result_view.set_markdown(result)
        
        func = self.tool_call.get('function', {})
        name = func.get('name', 'unknown_tool')
        self.toggle_btn.setText(f"✓ 已完成: {name}")

    def update_content(self):
        """Refresh content from tool_call data"""
        if 'result' in self.tool_call:
            self.set_result(self.tool_call['result'])


class ToolCallsSection(QWidget):
    """Container for multiple tool calls"""
    
    def __init__(self, tool_calls: List[dict], parent=None):
        super().__init__(parent)
        self.tool_calls = tool_calls
        self.items = {}
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)
        
        for tool_call in self.tool_calls:
            item = ToolCallItem(tool_call)
            self.items[tool_call.get('id')] = item
            layout.addWidget(item)
            
    def update_result(self, tool_id: str, result: str):
        if tool_id in self.items:
            self.items[tool_id].set_result(result)
            
    def refresh_all(self):
        """Refresh all items from their underlying data"""
        for item in self.items.values():
            item.update_content()


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

        # Model + timestamp (from metadata / created_at)
        self._add_model_badge(header)
        self._add_timestamp_badge(header)
        
        # Stats - compact badges
        if self.message.tokens:
            self._add_badge(header, f"T:{self.message.tokens}")
        
        if self.message.response_time_ms:
            self._add_badge(header, f"{self.message.response_time_ms / 1000:.1f}s")
        
        header.addStretch()

        # Keep action buttons tight and consistent with the nav toolbar.
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(2)
        self._add_action_buttons(actions_layout)
        header.addWidget(actions_widget)
        
        layout.addLayout(header)

        # Thinking (assistant only) - show above final content
        if (not is_user) and self.message.thinking:
            layout.addWidget(ThinkingSection(self.message.thinking))
        
        # Content
        # MarkdownView handles str conversion
        if self.message.content:
            content_view = MarkdownView(self.message.content)
            content_view.setObjectName("message_content")
            content_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            layout.addWidget(content_view)
        
        # Tool Calls (assistant only)
        if (not is_user) and self.message.tool_calls:
            self.tool_calls_widget = ToolCallsSection(self.message.tool_calls)
            layout.addWidget(self.tool_calls_widget)

        # Images
        if self.message.images:
            self._add_images(layout)

    def has_tool_call(self, tool_id: str) -> bool:
        """Check if this message contains a tool call with the given ID"""
        if not self.message.tool_calls:
            return False
        return any(tc.get('id') == tool_id for tc in self.message.tool_calls)

    def add_tool_result(self, tool_message: Message):
        """Update tool call UI with result"""
        if hasattr(self, 'tool_calls_widget') and tool_message.tool_call_id:
            self.tool_calls_widget.update_result(tool_message.tool_call_id, tool_message.content)

    def refresh_tool_calls(self):
        """Refresh tool calls display from message data"""
        if hasattr(self, 'tool_calls_widget'):
            self.tool_calls_widget.refresh_all()

    def _add_model_badge(self, layout):
        model = None
        if isinstance(self.message.metadata, dict):
            model = self.message.metadata.get('model') or self.message.metadata.get('model_name')
        if model:
            text = str(model)
            if len(text) > 22:
                text = text[:21] + "…"
            model_label = QLabel(text)
            model_label.setObjectName("message_badge")
            model_label.setToolTip(str(model))
            layout.addWidget(model_label)

    def _add_timestamp_badge(self, layout):
        try:
            ts = self.message.created_at.strftime('%m-%d %H:%M')
            self._add_badge(layout, ts)
        except Exception:
            pass

    def _add_badge(self, layout, text):
        label = QLabel(text)
        label.setObjectName("message_badge")
        layout.addWidget(label)

    def _add_action_buttons(self, layout):
        copy_btn = QToolButton()
        copy_btn.setText("⧉")
        copy_btn.setToolTip("复制原文")
        copy_btn.setFixedSize(24, 24)
        copy_btn.setObjectName("msg_copy_btn")
        copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        copy_btn.clicked.connect(self._copy_original_content)
        self._copy_btn = copy_btn
        layout.addWidget(copy_btn)
        
        edit_btn = QToolButton()
        edit_btn.setText("✎")
        edit_btn.setToolTip("编辑")
        edit_btn.setFixedSize(24, 24)
        edit_btn.setObjectName("msg_edit_btn")
        edit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.message.id))
        layout.addWidget(edit_btn)

        delete_btn = QToolButton()
        delete_btn.setText("✕")
        delete_btn.setToolTip("删除")
        delete_btn.setFixedSize(24, 24)
        delete_btn.setObjectName("msg_delete_btn")
        delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.message.id))
        layout.addWidget(delete_btn)

    def _add_images(self, layout):
        images_layout = QHBoxLayout()
        images_layout.setSpacing(4)
        for image_data in self.message.images[:4]:
            thumb = ImageThumbnail(image_data)
            thumb.clicked.connect(lambda _=None, d=image_data: self._open_image_preview(d))
            images_layout.addWidget(thumb)
        images_layout.addStretch()
        layout.addLayout(images_layout)

    def _copy_original_content(self) -> None:
        text = str(self.message.content or "")
        QGuiApplication.clipboard().setText(text)

        if not hasattr(self, "_copy_btn"):
            return

        try:
            self._copy_btn.setToolTip("已复制")
            QTimer.singleShot(1200, self._restore_copy_btn_tooltip)
        except RuntimeError:
            pass
    
    def _restore_copy_btn_tooltip(self):
        try:
            self._copy_btn.setToolTip("复制原文")
        except RuntimeError:
            pass

    def _open_image_preview(self, image_data: str):
        dialog = ImageViewerDialog(image_data, self)
        dialog.exec()
