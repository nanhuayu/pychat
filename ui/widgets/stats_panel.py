"""
Statistics panel for displaying chat metrics - Chinese UI
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame
)
from PyQt6.QtCore import Qt
from typing import Optional
from models.conversation import Conversation


class StatCard(QFrame):
    """A card displaying a single statistic"""
    
    def __init__(self, label: str, value: str = "-", parent=None):
        super().__init__(parent)
        self.setObjectName("stat_card")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        
        self.label = QLabel(label)
        self.label.setObjectName("stat_label")
        layout.addWidget(self.label)
        
        self.value_label = QLabel(value)
        self.value_label.setObjectName("stat_value")
        layout.addWidget(self.value_label)
    
    def set_value(self, value: str):
        self.value_label.setText(value)


class StatsPanel(QWidget):
    """Panel displaying conversation statistics"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stats_panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(180)
        self.setMaximumWidth(220)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        title = QLabel("统计信息")
        title.setObjectName("stats_title")
        layout.addWidget(title)
        
        self.total_messages = StatCard("消息数量")
        layout.addWidget(self.total_messages)
        
        self.total_tokens = StatCard("总 Token")
        layout.addWidget(self.total_tokens)
        
        self.avg_tokens = StatCard("平均 Token/消息")
        layout.addWidget(self.avg_tokens)
        
        self.tokens_per_min = StatCard("Token/分钟")
        layout.addWidget(self.tokens_per_min)
        
        self.last_response_time = StatCard("最近响应时间")
        layout.addWidget(self.last_response_time)
        
        model_title = QLabel("当前模型")
        model_title.setObjectName("stats_subtitle")
        layout.addWidget(model_title)
        
        self.model_label = QLabel("-")
        self.model_label.setObjectName("stats_model")
        self.model_label.setWordWrap(True)
        layout.addWidget(self.model_label)
        
        layout.addStretch()
    
    def update_stats(self, conversation: Optional[Conversation]):
        if not conversation:
            self._clear_stats()
            return
        
        msg_count = len(conversation.messages)
        self.total_messages.set_value(str(msg_count))
        
        total_tokens = sum(m.tokens or 0 for m in conversation.messages)
        self.total_tokens.set_value(f"{total_tokens:,}")
        
        if msg_count > 0:
            avg = total_tokens / msg_count
            self.avg_tokens.set_value(f"{avg:.1f}")
        else:
            self.avg_tokens.set_value("-")
        
        tpm = conversation.get_tokens_per_minute()
        if tpm > 0:
            self.tokens_per_min.set_value(f"{tpm:.1f}")
        else:
            self.tokens_per_min.set_value("-")
        
        last_assistant = None
        for msg in reversed(conversation.messages):
            if msg.role == 'assistant' and msg.response_time_ms:
                last_assistant = msg
                break
        
        if last_assistant and last_assistant.response_time_ms:
            time_sec = last_assistant.response_time_ms / 1000
            self.last_response_time.set_value(f"{time_sec:.2f}s")
        else:
            self.last_response_time.set_value("-")
        
        self.model_label.setText(conversation.model or "-")
    
    def update_streaming_stats(self, tokens: int, elapsed_ms: int):
        self.total_tokens.set_value(f"{tokens:,}")
        if elapsed_ms > 0:
            tpm = (tokens / elapsed_ms) * 60000
            self.tokens_per_min.set_value(f"{tpm:.1f}")
            time_sec = elapsed_ms / 1000
            self.last_response_time.set_value(f"{time_sec:.2f}s")
    
    def _clear_stats(self):
        self.total_messages.set_value("-")
        self.total_tokens.set_value("-")
        self.avg_tokens.set_value("-")
        self.tokens_per_min.set_value("-")
        self.last_response_time.set_value("-")
        self.model_label.setText("-")
