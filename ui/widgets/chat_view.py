"""
Chat view widget - Compact responsive layout
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QFrame, QSizePolicy, QPushButton, QToolButton
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QEvent
from typing import List
from datetime import datetime

from models.conversation import Message, Conversation
from .message_widget import MessageWidget, MarkdownView
from ui.utils.image_utils import extract_images_from_mime, extract_images_from_clipboard


class ChatView(QWidget):
    """Scrollable view for displaying chat messages"""
    
    edit_message = pyqtSignal(str)
    delete_message = pyqtSignal(str)
    images_dropped = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat_container")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._message_widgets: List[MessageWidget] = []
        self._nav_update_timer: QTimer | None = None
        self._streaming_label: QLabel = None
        self._streaming_thinking_label: QLabel = None
        self._streaming_thinking_btn: QPushButton = None
        self._streaming_thinking_expanded: bool = False
        self._streaming_container = None
        self._streaming_text: str = ""
        self._streaming_thinking_text: str = ""
        self._setup_ui()
    
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
        
        self.model_indicator = QLabel("未选择模型")
        self.model_indicator.setObjectName("model_indicator")
        header_layout.addWidget(self.model_indicator)
        
        header_layout.addStretch()

        # ===== Message navigation (toolbar-style group) =====
        nav_group = QFrame()
        nav_group.setObjectName("nav_group")
        nav_layout = QHBoxLayout(nav_group)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(2)

        self.nav_prev_btn = self._create_nav_button("◀", "上一条消息")
        self.nav_prev_btn.clicked.connect(self.go_prev_message)
        nav_layout.addWidget(self.nav_prev_btn)

        self.nav_next_btn = self._create_nav_button("▶", "下一条消息")
        self.nav_next_btn.clicked.connect(self.go_next_message)
        nav_layout.addWidget(self.nav_next_btn)

        self.nav_bottom_btn = self._create_nav_button("▶▶", "滚动到底部")
        self.nav_bottom_btn.clicked.connect(self._scroll_to_bottom)
        nav_layout.addWidget(self.nav_bottom_btn)

        header_layout.addWidget(nav_group)
        
        layout.addWidget(self.header_bar)
        
        # ===== Messages scroll area =====
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("messages_scroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.messages_container = QWidget()
        self.messages_container.setObjectName("messages_container")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(8, 8, 8, 8)
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
        except Exception:
            pass

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
                    except Exception:
                        pass

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
        except Exception:
            pass

        return super().eventFilter(watched, event)

    def _create_nav_button(self, text: str, tooltip: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tooltip)
        # Reuse the same style as InputArea toolbar for consistency.
        btn.setObjectName("toolbar_btn")
        btn.setFixedSize(24, 24)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return btn
    
    def update_header(self, provider_name: str = "", model: str = "", msg_count: int = 0):
        """Update header bar with current model info"""
        if provider_name and model:
            self.model_indicator.setText(f"🤖 {model} | {provider_name}")
        elif model:
            self.model_indicator.setText(f"🤖 {model}")
        else:
            self.model_indicator.setText("未选择模型")

        self._update_nav_state()
    
    def clear(self):
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._message_widgets.clear()
        self._streaming_label = None
        self._streaming_thinking_label = None
        self._streaming_thinking_btn = None
        self._streaming_thinking_expanded = False
        self._streaming_container = None
        self._streaming_text = ""
        self._streaming_thinking_text = ""
        self._update_nav_state()
    
    def load_conversation(self, conversation: Conversation):
        self.clear()
        for message in conversation.messages:
            self.add_message(message)
        QTimer.singleShot(100, self._scroll_to_bottom)
        self._schedule_nav_update()
    
    def add_message(self, message: Message):
        widget = MessageWidget(message)
        widget.edit_requested.connect(self.edit_message.emit)
        widget.delete_requested.connect(self.delete_message.emit)
        
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, widget)
        self._message_widgets.append(widget)
        QTimer.singleShot(50, self._scroll_to_bottom)
        self._schedule_nav_update()
    
    def start_streaming_response(self, model: str = ""):
        if self._streaming_label:
            return
        
        container = QFrame()
        container.setObjectName("streaming_container")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(10, 8, 10, 8)
        container_layout.setSpacing(4)
        
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        role_label = QLabel("助手")
        role_label.setObjectName("message_role")
        header_row.addWidget(role_label)

        if model:
            model_label = QLabel(model)
            model_label.setObjectName("message_badge")
            model_label.setToolTip(model)
            header_row.addWidget(model_label)

        ts = datetime.now().strftime('%m-%d %H:%M')
        ts_label = QLabel(ts)
        ts_label.setObjectName("message_badge")
        header_row.addWidget(ts_label)

        header_row.addStretch()
        container_layout.addLayout(header_row)

        # Thinking (streaming) - collapsible (show above content)
        self._streaming_thinking_btn = QPushButton("思考")
        self._streaming_thinking_btn.setObjectName("thinking_toggle")
        self._streaming_thinking_btn.setVisible(False)
        self._streaming_thinking_btn.clicked.connect(self._toggle_streaming_thinking)
        container_layout.addWidget(self._streaming_thinking_btn)

        self._streaming_thinking_label = MarkdownView("")
        self._streaming_thinking_label.setObjectName("thinking_content")
        self._streaming_thinking_label.setVisible(False)
        container_layout.addWidget(self._streaming_thinking_label)

        self._streaming_label = MarkdownView("正在生成...")
        self._streaming_label.setObjectName("message_content")
        self._streaming_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        container_layout.addWidget(self._streaming_label)

        self._streaming_text = ""
        self._streaming_thinking_text = ""
        
        self._streaming_container = container
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, container)
        QTimer.singleShot(50, self._scroll_to_bottom)
    
    def append_streaming_content(self, content: str):
        if self._streaming_label and content is not None:
            self._streaming_text += str(content)
            self._streaming_label.set_markdown(self._streaming_text or "正在生成...")
            QTimer.singleShot(10, self._scroll_to_bottom)

    def append_streaming_thinking(self, thinking: str):
        if not self._streaming_thinking_label or not thinking:
            return

        self._streaming_thinking_text += str(thinking)
        self._streaming_thinking_label.set_markdown(self._streaming_thinking_text)
        if self._streaming_thinking_btn:
            self._streaming_thinking_btn.setVisible(True)

        # Show thinking in real-time during streaming.
        if not self._streaming_thinking_expanded:
            self._streaming_thinking_expanded = True
            self._streaming_thinking_label.setVisible(True)
            if self._streaming_thinking_btn:
                self._streaming_thinking_btn.setText("收起思考")

        QTimer.singleShot(10, self._scroll_to_bottom)

    def restore_streaming_state(self, visible_text: str = "", thinking_text: str = "") -> None:
        """Restore streaming UI from cached buffers (used when switching back to a streaming conversation)."""
        if not self._streaming_label:
            # Caller should create the container via start_streaming_response(model=...).
            return

        self._streaming_text = str(visible_text or "")
        self._streaming_label.set_markdown(self._streaming_text or "正在生成...")

        self._streaming_thinking_text = str(thinking_text or "")
        if self._streaming_thinking_label and self._streaming_thinking_btn:
            if self._streaming_thinking_text:
                self._streaming_thinking_label.set_markdown(self._streaming_thinking_text)
                self._streaming_thinking_btn.setVisible(True)
                self._streaming_thinking_expanded = True
                self._streaming_thinking_label.setVisible(True)
                self._streaming_thinking_btn.setText("收起思考")
            else:
                self._streaming_thinking_btn.setVisible(False)
                self._streaming_thinking_expanded = False
                self._streaming_thinking_label.setVisible(False)
                self._streaming_thinking_btn.setText("思考")

        QTimer.singleShot(10, self._scroll_to_bottom)

    def _toggle_streaming_thinking(self):
        if not self._streaming_thinking_label or not self._streaming_thinking_btn:
            return
        self._streaming_thinking_expanded = not self._streaming_thinking_expanded
        self._streaming_thinking_label.setVisible(self._streaming_thinking_expanded)
        self._streaming_thinking_btn.setText("收起思考" if self._streaming_thinking_expanded else "思考")
    
    def finish_streaming_response(self, message: Message):
        if self._streaming_container:
            self._streaming_container.deleteLater()
            self._streaming_container = None
        self._streaming_label = None
        self._streaming_thinking_label = None
        self._streaming_thinking_btn = None
        self._streaming_thinking_expanded = False
        self._streaming_text = ""
        self._streaming_thinking_text = ""
        self.add_message(message)
        self._schedule_nav_update()
    
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
            self.nav_prev_btn.setEnabled(False)
            self.nav_next_btn.setEnabled(False)
            self.nav_bottom_btn.setEnabled(False)
            self.nav_prev_btn.setToolTip("上一条消息")
            self.nav_next_btn.setToolTip("下一条消息")
            self.nav_bottom_btn.setToolTip("滚动到底部")
            return

        idx = self._find_current_message_index()
        if idx < 0:
            idx = 0

        self.nav_prev_btn.setEnabled(idx > 0)
        self.nav_next_btn.setEnabled(idx < total - 1)
        self.nav_bottom_btn.setEnabled(True)

        # Keep the UI minimal: show position in tooltips instead of an always-visible counter.
        pos_text = f"{idx + 1}/{total}"
        self.nav_prev_btn.setToolTip(f"上一条消息 ({pos_text})")
        self.nav_next_btn.setToolTip(f"下一条消息 ({pos_text})")
        self.nav_bottom_btn.setToolTip(f"滚动到底部 (共 {total} 条)")
    
    def _scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
