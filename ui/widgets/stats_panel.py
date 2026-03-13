"""Right sidebar panel.

Shows the current conversation's active tasks (SessionState) and metrics.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QToolButton,
    QLineEdit,
    QScrollArea,
)

from models.conversation import Conversation
from models.state import TaskStatus


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
    """Panel displaying conversation state + statistics."""

    task_create_requested = pyqtSignal(str)
    task_complete_requested = pyqtSignal(str)
    task_delete_requested = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stats_panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(200)
        self.setMaximumWidth(300)
        self._conversation: Optional[Conversation] = None
        self._setup_ui()
    
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("stats_scroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll)

        content = QWidget()
        content.setObjectName("stats_scroll_content")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.tasks_title = QLabel("任务")
        self.tasks_title.setObjectName("stats_title")
        layout.addWidget(self.tasks_title)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)

        self.new_task_edit = QLineEdit()
        self.new_task_edit.setObjectName("new_task_edit")
        self.new_task_edit.setPlaceholderText("新增任务…")
        self.new_task_edit.returnPressed.connect(self._emit_create_task)
        add_row.addWidget(self.new_task_edit, 1)

        self.add_task_btn = QToolButton()
        self.add_task_btn.setObjectName("add_task_btn")
        self.add_task_btn.setText("+")
        self.add_task_btn.setAutoRaise(True)
        self.add_task_btn.setFixedSize(22, 22)
        self.add_task_btn.clicked.connect(self._emit_create_task)
        add_row.addWidget(self.add_task_btn)

        layout.addLayout(add_row)

        self.tasks_container = QFrame()
        self.tasks_container.setObjectName("tasks_container")
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setContentsMargins(0, 0, 0, 0)
        self.tasks_layout.setSpacing(6)
        layout.addWidget(self.tasks_container)

        self.memory_title = QLabel("记忆")
        self.memory_title.setObjectName("stats_subtitle")
        layout.addWidget(self.memory_title)

        self.memory_container = QFrame()
        self.memory_container.setObjectName("memory_container")
        self.memory_layout = QVBoxLayout(self.memory_container)
        self.memory_layout.setContentsMargins(0, 0, 0, 0)
        self.memory_layout.setSpacing(6)
        layout.addWidget(self.memory_container)

        self.documents_title = QLabel("文档")
        self.documents_title.setObjectName("stats_subtitle")
        layout.addWidget(self.documents_title)

        self.documents_container = QFrame()
        self.documents_container.setObjectName("documents_container")
        self.documents_layout = QVBoxLayout(self.documents_container)
        self.documents_layout.setContentsMargins(0, 0, 0, 0)
        self.documents_layout.setSpacing(6)
        layout.addWidget(self.documents_container)

        metrics_title = QLabel("统计信息")
        metrics_title.setObjectName("stats_subtitle")
        layout.addWidget(metrics_title)
        
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
        
        layout.addStretch(1)

        self._render_tasks(None)
        self._render_memory(None)
        self._render_documents(None)
        self._set_task_controls_enabled(False)

    def _set_task_controls_enabled(self, enabled: bool) -> None:
        self.new_task_edit.setEnabled(bool(enabled))
        self.add_task_btn.setEnabled(bool(enabled))

    def _emit_create_task(self) -> None:
        if not self._conversation:
            return
        text = (self.new_task_edit.text() or "").strip()
        if not text:
            return
        self.new_task_edit.setText("")
        self.task_create_requested.emit(text)

    def _render_tasks(self, conversation: Optional[Conversation]) -> None:
        # clear
        while self.tasks_layout.count():
            item = self.tasks_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not conversation:
            self.tasks_title.setText("任务")
            empty = QLabel("-")
            empty.setProperty("muted", True)
            self.tasks_layout.addWidget(empty)
            return

        try:
            state = conversation.get_state()
            active_tasks = list(state.get_active_tasks() or [])
        except Exception:
            active_tasks = []

        self.tasks_title.setText(f"任务 ({len(active_tasks)})")
        if not active_tasks:
            empty = QLabel("暂无进行中的任务")
            empty.setProperty("muted", True)
            self.tasks_layout.addWidget(empty)
            return

        # show top N for compactness
        max_show = 6
        shown = active_tasks[:max_show]
        rest = len(active_tasks) - len(shown)

        for t in shown:
            row = QFrame()
            row.setObjectName("task_card")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(6)

            status_icon = "⏳" if getattr(t, "status", None) == TaskStatus.IN_PROGRESS else "⬜"
            text = f"{status_icon} {getattr(t, 'content', '')}".strip()
            lbl = QLabel(text)
            lbl.setObjectName("task_text")
            lbl.setWordWrap(True)
            row_layout.addWidget(lbl, 1)

            done_btn = QToolButton()
            done_btn.setObjectName("task_done_btn")
            done_btn.setText("✓")
            done_btn.setAutoRaise(True)
            done_btn.setFixedSize(22, 22)
            done_btn.setToolTip("标记完成")
            done_btn.clicked.connect(lambda _=False, task_id=getattr(t, 'id', ''): self.task_complete_requested.emit(task_id))
            row_layout.addWidget(done_btn)

            del_btn = QToolButton()
            del_btn.setObjectName("task_delete_btn")
            del_btn.setText("×")
            del_btn.setAutoRaise(True)
            del_btn.setFixedSize(22, 22)
            del_btn.setToolTip("删除")
            del_btn.clicked.connect(lambda _=False, task_id=getattr(t, 'id', ''): self.task_delete_requested.emit(task_id))
            row_layout.addWidget(del_btn)

            self.tasks_layout.addWidget(row)

        if rest > 0:
            more = QLabel(f"+{rest} 个任务未显示")
            more.setProperty("muted", True)
            self.tasks_layout.addWidget(more)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_memory(self, conversation: Optional[Conversation]) -> None:
        self._clear_layout(self.memory_layout)

        if not conversation:
            empty = QLabel("-")
            empty.setProperty("muted", True)
            self.memory_layout.addWidget(empty)
            return

        try:
            memory = dict((conversation.get_state().memory or {}))
        except Exception:
            memory = {}

        self.memory_title.setText(f"记忆 ({len(memory)})")
        if not memory:
            empty = QLabel("暂无记忆条目")
            empty.setProperty("muted", True)
            self.memory_layout.addWidget(empty)
            return

        for key, value in list(memory.items())[:5]:
            card = QFrame()
            card.setObjectName("task_card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(4)

            key_label = QLabel(str(key))
            key_label.setObjectName("task_text")
            card_layout.addWidget(key_label)

            preview = str(value or "")
            if len(preview) > 100:
                preview = preview[:100] + "..."
            value_label = QLabel(preview or "-")
            value_label.setWordWrap(True)
            value_label.setProperty("muted", True)
            card_layout.addWidget(value_label)

            self.memory_layout.addWidget(card)

    def _render_documents(self, conversation: Optional[Conversation]) -> None:
        self._clear_layout(self.documents_layout)

        if not conversation:
            empty = QLabel("-")
            empty.setProperty("muted", True)
            self.documents_layout.addWidget(empty)
            return

        try:
            documents = dict((conversation.get_state().documents or {}))
        except Exception:
            documents = {}

        self.documents_title.setText(f"文档 ({len(documents)})")
        if not documents:
            empty = QLabel("暂无会话文档")
            empty.setProperty("muted", True)
            self.documents_layout.addWidget(empty)
            return

        for name, doc in list(documents.items())[:4]:
            card = QFrame()
            card.setObjectName("task_card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(4)

            name_label = QLabel(str(name))
            name_label.setObjectName("task_text")
            card_layout.addWidget(name_label)

            preview = str(getattr(doc, 'content', '') or '')
            if len(preview) > 140:
                preview = preview[:140] + "..."
            content_label = QLabel(preview or "-")
            content_label.setWordWrap(True)
            content_label.setProperty("muted", True)
            card_layout.addWidget(content_label)

            self.documents_layout.addWidget(card)
    
    def update_stats(self, conversation: Optional[Conversation]):
        self._conversation = conversation
        self._set_task_controls_enabled(bool(conversation))
        self._render_tasks(conversation)
        self._render_memory(conversation)
        self._render_documents(conversation)
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
