"""
Sidebar widget for conversation list and management - Chinese UI
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QFileDialog, QLabel
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QAction
from typing import Dict, Any, List
from datetime import datetime


class ConversationItem(QListWidgetItem):
    """Custom list item for conversations - compact display"""
    
    def __init__(self, data: Dict[str, Any]):
        super().__init__()
        self.data = data
        title = data.get('title', '无标题')
        model = data.get('model', '')
        updated_at = data.get('updated_at') or data.get('created_at')
        updated_str = ""
        if isinstance(updated_at, str) and updated_at:
            try:
                dt = datetime.fromisoformat(updated_at)
                updated_str = dt.strftime('%m-%d %H:%M')
            except Exception:
                updated_str = ""

        # Only show title + time (no model for compact view)
        self.setText(title + ("\n" + updated_str if updated_str else ""))
        count = data.get('message_count', 0)
        self.setToolTip(f"模型: {model or '未设置'}\n消息: {count} 条\n更新: {updated_str}")


class Sidebar(QWidget):
    """Sidebar with conversation list"""
    
    conversation_selected = pyqtSignal(str)
    new_conversation = pyqtSignal()
    import_conversation = pyqtSignal(str)
    delete_conversation = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(160)
        self.setMaximumWidth(260)
        self._all_conversations = []
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setObjectName("sidebar_header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 6)
        header_layout.setSpacing(6)
        
        # title = QLabel("PyChat")
        # title.setObjectName("sidebar_title")
        # header_layout.addWidget(title)
        
        self.new_chat_btn = QPushButton("+ 新建会话")
        self.new_chat_btn.setObjectName("new_chat_btn")
        self.new_chat_btn.clicked.connect(self.new_conversation.emit)
        header_layout.addWidget(self.new_chat_btn)
        
        self.search_input = QLineEdit()
        self.search_input.setObjectName("search_input")
        self.search_input.setPlaceholderText("搜索会话...")
        self.search_input.textChanged.connect(self._filter_conversations)
        header_layout.addWidget(self.search_input)
        
        layout.addWidget(header)
        
        # Conversation list
        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("conversation_list")
        self.conversation_list.itemClicked.connect(self._on_item_clicked)
        self.conversation_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.conversation_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.conversation_list)
        
        # Footer
        footer = QWidget()
        footer.setObjectName("sidebar_footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 6, 10, 10)
        
        import_btn = QPushButton("导入 JSON")
        import_btn.setObjectName("import_btn")
        import_btn.clicked.connect(self._import_conversation)
        footer_layout.addWidget(import_btn)
        
        layout.addWidget(footer)
    
    def update_conversations(self, conversations: List[Dict[str, Any]]):
        self.conversation_list.clear()
        self._all_conversations = conversations
        
        for conv in conversations:
            item = ConversationItem(conv)
            self.conversation_list.addItem(item)
    
    def select_conversation(self, conversation_id: str):
        for i in range(self.conversation_list.count()):
            item = self.conversation_list.item(i)
            if isinstance(item, ConversationItem) and item.data.get('id') == conversation_id:
                self.conversation_list.setCurrentItem(item)
                break
    
    def _filter_conversations(self, text: str):
        text = text.lower()
        for i in range(self.conversation_list.count()):
            item = self.conversation_list.item(i)
            if isinstance(item, ConversationItem):
                title = item.data.get('title', '').lower()
                item.setHidden(text not in title)
    
    def _on_item_clicked(self, item: QListWidgetItem):
        if isinstance(item, ConversationItem):
            self.conversation_selected.emit(item.data.get('id', ''))
    
    def _show_context_menu(self, position):
        item = self.conversation_list.itemAt(position)
        if not isinstance(item, ConversationItem):
            return
        
        menu = QMenu(self)
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(
            lambda: self._confirm_delete(item.data.get('id', ''))
        )
        menu.addAction(delete_action)
        menu.exec(self.conversation_list.mapToGlobal(position))
    
    def _confirm_delete(self, conversation_id: str):
        reply = QMessageBox.question(
            self, '删除会话',
            '确定要删除这个会话吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_conversation.emit(conversation_id)
    
    def _import_conversation(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, '导入会话', '',
            'JSON 文件 (*.json);;所有文件 (*)'
        )
        if file_path:
            self.import_conversation.emit(file_path)
