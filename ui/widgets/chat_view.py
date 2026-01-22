"""
Chat view widget - Compact responsive layout
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QFrame, QSizePolicy, QPushButton
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from typing import List
from datetime import datetime

from models.conversation import Message, Conversation
from .message_widget import MessageWidget, MarkdownView


class ChatView(QWidget):
    """Scrollable view for displaying chat messages"""
    
    edit_message = pyqtSignal(str)
    delete_message = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat_container")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._message_widgets: List[MessageWidget] = []
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
        
        self.context_indicator = QLabel("")
        self.context_indicator.setObjectName("context_indicator")
        header_layout.addWidget(self.context_indicator)
        
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
    
    def update_header(self, provider_name: str = "", model: str = "", msg_count: int = 0):
        """Update header bar with current model info"""
        if provider_name and model:
            self.model_indicator.setText(f"🤖 {model} | {provider_name}")
        elif model:
            self.model_indicator.setText(f"🤖 {model}")
        else:
            self.model_indicator.setText("未选择模型")
        
        if msg_count > 0:
            self.context_indicator.setText(f"📝 {msg_count} 条消息")
        else:
            self.context_indicator.setText("")
    
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
    
    def load_conversation(self, conversation: Conversation):
        self.clear()
        for message in conversation.messages:
            self.add_message(message)
        QTimer.singleShot(100, self._scroll_to_bottom)
    
    def add_message(self, message: Message):
        widget = MessageWidget(message)
        widget.edit_requested.connect(self.edit_message.emit)
        widget.delete_requested.connect(self.delete_message.emit)
        
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, widget)
        self._message_widgets.append(widget)
        QTimer.singleShot(50, self._scroll_to_bottom)
    
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
    
    def remove_message(self, message_id: str):
        for widget in self._message_widgets[:]:
            if widget.message.id == message_id:
                widget.deleteLater()
                self._message_widgets.remove(widget)
                break
    
    def _scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
