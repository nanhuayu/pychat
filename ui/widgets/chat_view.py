"""
Chat view widget - Compact responsive layout
"""

import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QFrame, QSizePolicy, QPushButton, QToolButton, QFileDialog
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QEvent
from typing import List
import os

from models.conversation import Message, Conversation
from .message_widget import MessageWidget, MarkdownView
from .chat.streaming_overlay import StreamingOverlay
from ui.utils.image_utils import extract_images_from_mime, extract_images_from_clipboard


logger = logging.getLogger(__name__)


class ChatView(QWidget):
    """Scrollable view for displaying chat messages"""
    
    edit_message = pyqtSignal(str)
    delete_message = pyqtSignal(str)
    images_dropped = pyqtSignal(list)
    work_dir_changed = pyqtSignal(str)  # Signal emitted when workspace directory changes
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat_container")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._message_widgets: List[MessageWidget] = []
        self._nav_update_timer: QTimer | None = None
        self._stream = StreamingOverlay(scroll_area=None)  # scroll_area set after _setup_ui
        
        self._setup_ui()
        self._stream._scroll_area = self.scroll_area
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # ===== Header bar with model indicator =====
        self.header_bar = QFrame()
        self.header_bar.setObjectName("chat_header")
        self.header_bar.setFixedHeight(32)
        
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.setSpacing(6)
        
        # ===== Workspace/Folder Button =====
        self.work_dir_btn = QPushButton("📁 未设置工作区")
        self.work_dir_btn.setObjectName("work_dir_btn")
        self.work_dir_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.work_dir_btn.setToolTip("点击设置当前会话的工作目录 (用于 MCP/CMD 执行)")
        self.work_dir_btn.clicked.connect(self._select_work_dir)
        # Style: transparent background, icon + text
        self.work_dir_btn.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 4px;
                padding: 2px 8px;
                text-align: left;
                font-size: 12px;
                color: #666;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 0.05);
                color: #333;
            }
        """)
        header_layout.addWidget(self.work_dir_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedHeight(16)
        sep.setStyleSheet("color: #ccc;")
        header_layout.addWidget(sep)

        self.model_indicator = QLabel("未选择模型")
        self.model_indicator.setObjectName("model_indicator")
        header_layout.addWidget(self.model_indicator)
        
        header_layout.addStretch()

        # ===== Message navigation (toolbar-style group) =====
        header_layout.addWidget(self._create_nav_bar())
        
        layout.addWidget(self.header_bar)
        
        # ===== Messages scroll area =====
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("messages_scroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.messages_container = QWidget()
        self.messages_container.setObjectName("messages_container")
        self.messages_layout = QVBoxLayout(self.messages_container)
        # Align list padding with header bar margins for a cleaner vertical rhythm.
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.messages_layout.setSpacing(6)
        self.messages_layout.addStretch()
        
        self.scroll_area.setWidget(self.messages_container)
        layout.addWidget(self.scroll_area)

        # Allow dropping images anywhere in the chat area (message list viewport)
        try:
            self.scroll_area.setAcceptDrops(True)
            self.scroll_area.viewport().setAcceptDrops(True)
            self.scroll_area.viewport().installEventFilter(self)
            self.scroll_area.viewport().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        except Exception as exc:
            logger.debug("Failed to enable drag-and-drop on chat view: %s", exc)

        # Debounced nav state updates (scrolling can emit valueChanged frequently)
        self._nav_update_timer = QTimer(self)
        self._nav_update_timer.setSingleShot(True)
        self._nav_update_timer.timeout.connect(self._update_nav_state)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._schedule_nav_update)

        self._update_nav_state()

    def eventFilter(self, watched, event):
        # Handle drag/drop on the scroll area viewport (the actual visible chat area).
        try:
            if watched == self.scroll_area.viewport():
                if event.type() == QEvent.Type.KeyPress:
                    # Allow pasting screenshot images when focus is on the chat area.
                    try:
                        key = event.key()
                        mods = event.modifiers()
                        if key == Qt.Key.Key_V and (mods & Qt.KeyboardModifier.ControlModifier):
                            sources = extract_images_from_clipboard()
                            if sources:
                                self.images_dropped.emit(sources)
                                return True
                    except Exception as exc:
                        logger.debug("Failed to handle chat view clipboard paste: %s", exc)

                if event.type() == QEvent.Type.DragEnter:
                    md = event.mimeData()
                    data_urls, file_paths = extract_images_from_mime(md)
                    if data_urls or file_paths:
                        event.acceptProposedAction()
                        return True
                elif event.type() == QEvent.Type.Drop:
                    md = event.mimeData()
                    data_urls, file_paths = extract_images_from_mime(md)
                    sources = data_urls + file_paths
                    if sources:
                        event.acceptProposedAction()
                        self.images_dropped.emit(sources)
                        return True
        except Exception as exc:
            logger.debug("Failed during chat view drag/drop event handling: %s", exc)

        return super().eventFilter(watched, event)

    def _create_nav_bar(self) -> QWidget:
        nav_group = QFrame()
        nav_group.setObjectName("nav_group")
        nav_layout = QHBoxLayout(nav_group)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(2)

        self.nav_top_btn = self._create_nav_button("◀◀", "滚动到顶部")
        self.nav_top_btn.clicked.connect(self._scroll_to_top)
        nav_layout.addWidget(self.nav_top_btn)

        self.nav_prev_btn = self._create_nav_button("◀", "上一条消息")
        self.nav_prev_btn.clicked.connect(self.go_prev_message)
        nav_layout.addWidget(self.nav_prev_btn)

        self.nav_next_btn = self._create_nav_button("▶", "下一条消息")
        self.nav_next_btn.clicked.connect(self.go_next_message)
        nav_layout.addWidget(self.nav_next_btn)

        self.nav_bottom_btn = self._create_nav_button("▶▶", "滚动到底部")
        self.nav_bottom_btn.clicked.connect(self._scroll_to_bottom)
        nav_layout.addWidget(self.nav_bottom_btn)
        
        return nav_group

    def _create_nav_button(self, text: str, tooltip: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tooltip)
        # Reuse the same style as InputArea toolbar for consistency.
        btn.setObjectName("toolbar_btn")
        btn.setFixedSize(24, 24)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return btn
    
    def _select_work_dir(self):
        """Open dialog to select workspace directory"""
        current_dir = ""
        # Try to get current path from button tooltip or text if possible, 
        # but better to rely on state passed from controller. 
        # For now, start from current working directory or last used.
        
        path = QFileDialog.getExistingDirectory(
            self, 
            "选择工作区文件夹",
            current_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        )
        
        if path:
            self.update_work_dir(path)
            self.work_dir_changed.emit(path)

    def update_work_dir(self, path: str):
        """Update workspace directory display"""
        if not path:
            self.work_dir_btn.setText("📁 未设置工作区")
            self.work_dir_btn.setToolTip("点击设置当前会话的工作目录")
        else:
            name = os.path.basename(path)
            if not name: # Root directory like C:/
                name = path
            self.work_dir_btn.setText(f"📁 {name}")
            self.work_dir_btn.setToolTip(f"工作区: {path}")

    def update_header(self, provider_name: str, model: str, msg_count: int = 0):
        """Update header info"""
        text = f"{provider_name} / {model}" if provider_name else model or "未选择模型"
        if msg_count > 0:
            text += f" ({msg_count})"
        self.model_indicator.setText(text)
        self.model_indicator.setToolTip(text)
    
    def clear(self):
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._message_widgets.clear()
        self._stream.finish()
        self._update_nav_state()
    
    def load_conversation(self, conversation: Conversation):
        self.clear()
        for message in conversation.messages:
            self.add_message(message)
        QTimer.singleShot(100, self._scroll_to_bottom)
        self._schedule_nav_update()
    
    def add_message(self, message: Message):
        # Try to update existing assistant message if this is a tool result
        if message.role == 'tool' and message.tool_call_id:
            # Search backwards for the matching assistant widget
            for i in range(len(self._message_widgets) - 1, -1, -1):
                widget = self._message_widgets[i]
                if widget.message.role == 'assistant' and widget.has_tool_call(message.tool_call_id):
                    # The message object in widget should already be updated by Conversation.add_message
                    # because it's the same object reference. We just need to refresh the UI.
                    widget.refresh_tool_calls()
                    
                    # Only auto-scroll if we updated the very last message
                    if i == len(self._message_widgets) - 1:
                        QTimer.singleShot(50, self._scroll_to_bottom)
                    return

        # Create widget
        widget = MessageWidget(message)
        widget.edit_requested.connect(self.edit_message.emit)
        widget.delete_requested.connect(self.delete_message.emit)
        
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, widget)
        self._message_widgets.append(widget)
        QTimer.singleShot(50, self._scroll_to_bottom)
        self._schedule_nav_update()
    
    def start_streaming_response(self, model: str = ""):
        self._stream.start(model=model, parent_layout=self.messages_layout)
    
    def append_streaming_content(self, content: str):
        self._stream.append_content(content)

    def append_streaming_thinking(self, thinking: str):
        self._stream.append_thinking(thinking)

    def restore_streaming_state(self, visible_text: str = "", thinking_text: str = "") -> None:
        """Restore streaming UI from cached buffers (used when switching back to a streaming conversation)."""
        self._stream.restore(visible_text, thinking_text)

    def finish_streaming_response(self, message: Message, add_to_view: bool = True):
        self._stream.finish()
        
        # Only add message to view if requested (to avoid duplicates)
        if add_to_view:
            self.add_message(message)
        self._schedule_nav_update()
    
    def is_streaming(self) -> bool:
        """Check if currently in streaming mode."""
        return self._stream.active

    def update_message(self, message: Message):
        for i, widget in enumerate(self._message_widgets):
            if widget.message.id == message.id:
                index = self.messages_layout.indexOf(widget)
                widget.deleteLater()
                
                new_widget = MessageWidget(message)
                new_widget.edit_requested.connect(self.edit_message.emit)
                new_widget.delete_requested.connect(self.delete_message.emit)
                
                self.messages_layout.insertWidget(index, new_widget)
                self._message_widgets[i] = new_widget
                break
            self._schedule_nav_update()
    
    def remove_message(self, message_id: str):
        for widget in self._message_widgets[:]:
            if widget.message.id == message_id:
                widget.deleteLater()
                self._message_widgets.remove(widget)
                break
        self._schedule_nav_update()

    def _schedule_nav_update(self):
        if not self._nav_update_timer:
            return
        self._nav_update_timer.start(30)

    def _navigable_widgets(self) -> List[MessageWidget]:
        return [w for w in self._message_widgets if w is not None]

    def _find_current_message_index(self) -> int:
        widgets = self._navigable_widgets()
        if not widgets:
            return -1

        scrollbar = self.scroll_area.verticalScrollBar()
        top = int(scrollbar.value()) + 2

        for i, w in enumerate(widgets):
            try:
                if (w.y() + w.height()) >= top:
                    return i
            except Exception:
                continue
        return len(widgets) - 1

    def _scroll_to_message_index(self, index: int):
        widgets = self._navigable_widgets()
        if not widgets:
            return

        index = max(0, min(int(index), len(widgets) - 1))
        w = widgets[index]
        try:
            y = max(int(w.y()) - 4, 0)
        except Exception:
            return

        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(y)
        self._schedule_nav_update()

    def go_prev_message(self):
        idx = self._find_current_message_index()
        if idx <= 0:
            return
        self._scroll_to_message_index(idx - 1)

    def go_next_message(self):
        widgets = self._navigable_widgets()
        if not widgets:
            return
        idx = self._find_current_message_index()
        if idx < 0:
            self._scroll_to_message_index(0)
            return
        if idx >= (len(widgets) - 1):
            return
        self._scroll_to_message_index(idx + 1)

    def _update_nav_state(self):
        widgets = self._navigable_widgets()
        total = len(widgets)
        if total <= 0:
            self.nav_top_btn.setEnabled(False)
            self.nav_prev_btn.setEnabled(False)
            self.nav_next_btn.setEnabled(False)
            self.nav_bottom_btn.setEnabled(False)
            
            self.nav_top_btn.setToolTip("滚动到顶部")
            self.nav_prev_btn.setToolTip("上一条消息")
            self.nav_next_btn.setToolTip("下一条消息")
            self.nav_bottom_btn.setToolTip("滚动到底部")
            return

        idx = self._find_current_message_index()
        if idx < 0:
            idx = 0

        self.nav_top_btn.setEnabled(True)
        self.nav_prev_btn.setEnabled(idx > 0)
        self.nav_next_btn.setEnabled(idx < total - 1)
        self.nav_bottom_btn.setEnabled(True)

        # Keep the UI minimal: show position in tooltips instead of an always-visible counter.
        pos_text = f"{idx + 1}/{total}"
        self.nav_top_btn.setToolTip(f"滚动到顶部 (共 {total} 条)")
        self.nav_prev_btn.setToolTip(f"上一条消息 ({pos_text})")
        self.nav_next_btn.setToolTip(f"下一条消息 ({pos_text})")
        self.nav_bottom_btn.setToolTip(f"滚动到底部 (共 {total} 条)")
    
    def _scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _scroll_to_top(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.minimum())

