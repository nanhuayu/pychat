"""
Input area widget - Compact responsive layout
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTextEdit, QLabel, QFileDialog, QComboBox,
    QFrame, QSizePolicy, QToolButton, QListWidget,
    QAbstractItemView,
    QStyle,
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize, QStringListModel, QRect
from PyQt6.QtGui import QKeyEvent, QDragEnterEvent, QDropEvent, QTextCursor
import os
from typing import Any, Callable, Dict, List, Optional

from core.commands import CommandRegistry
from core.modes.manager import ModeManager
from core.modes.features import get_mode_feature_policy, clamp_feature_flags
from core.task.types import RunPolicy
from core.task.builder import build_run_policy
from core.commands.mentions import MentionCandidate, MentionKind, MentionQuery

from ui.utils.image_utils import extract_images_from_mime, is_supported_image_path
from ui.utils.image_loader import load_pixmap


class AttachmentPreviewItem(QFrame):
    """Preview item for attached images or files."""

    remove_requested = pyqtSignal(str)

    def __init__(self, source: str, is_image: bool = True, parent=None):
        super().__init__(parent)
        self.source = source
        self.is_image = is_image
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("image_preview_item")
        self.setFixedSize(60, 56)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        thumb = QLabel()
        thumb.setObjectName("image_thumb")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self.is_image:
            pixmap = load_pixmap(self.source)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    56,
                    38,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                thumb.setPixmap(scaled)
            else:
                thumb.setText("IMG")
        else:
            ext = os.path.splitext(self.source)[1].lower() or "FILE"
            thumb.setText(ext)
            thumb.setStyleSheet("font-size: 10px; font-weight: bold; color: #555;")
            thumb.setToolTip(os.path.basename(self.source))

        layout.addWidget(thumb)

        if not self.is_image:
            name_lbl = QLabel(os.path.basename(self.source))
            name_lbl.setObjectName("file_name_lbl")
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet("font-size: 9px; color: #666;")
            font_metrics = name_lbl.fontMetrics()
            elided = name_lbl.fontMetrics().elidedText(
                name_lbl.text(),
                Qt.TextElideMode.ElideMiddle,
                56,
            )
            name_lbl.setText(elided)
            layout.addWidget(name_lbl)

        remove_btn = QPushButton("×")
        remove_btn.setObjectName("image_remove_btn")
        remove_btn.setFixedSize(14, 14)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.source))
        remove_btn.setParent(self)
        remove_btn.move(self.width() - 16, 2)
        remove_btn.show()


class AttachmentPreviewStrip(QWidget):
    """Preview strip for attached files/images."""

    remove_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("image_preview")
        self._items: dict[str, AttachmentPreviewItem] = {}

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 0, 4, 0)
        self._layout.setSpacing(4)
        self._layout.addStretch()
        self.setVisible(False)

    def add_attachment(self, source: str, *, is_image: bool) -> None:
        if source in self._items:
            return

        item = AttachmentPreviewItem(source, is_image=is_image)
        item.remove_requested.connect(self.remove_requested.emit)
        self._items[source] = item
        self._layout.insertWidget(self._layout.count() - 1, item)
        self.setVisible(True)

    def remove_attachment(self, source: str) -> None:
        item = self._items.pop(source, None)
        if item is not None:
            item.deleteLater()
        if not self._items:
            self.setVisible(False)

    def clear_attachments(self) -> None:
        for source in list(self._items.keys()):
            self.remove_attachment(source)


class ComposerToolbar(QWidget):
    """Toolbar widget for provider/model/mode controls."""

    attach_requested = pyqtSignal()
    conversation_settings_requested = pyqtSignal()
    provider_settings_requested = pyqtSignal()
    prompt_optimize_requested = pyqtSignal()
    send_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.attach_btn = self._make_button("📎", "添加文件/图片")
        self.attach_btn.clicked.connect(self.attach_requested.emit)
        layout.addWidget(self.attach_btn)

        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("provider_combo")
        self.provider_combo.setMinimumWidth(70)
        self.provider_combo.setMaximumWidth(110)
        layout.addWidget(self.provider_combo)

        self.model_combo = QComboBox()
        self.model_combo.setObjectName("model_combo")
        self.model_combo.setMinimumWidth(120)
        self.model_combo.setMaximumWidth(200)
        self.model_combo.setEditable(True)
        layout.addWidget(self.model_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("mode_combo")
        self.mode_combo.setMinimumWidth(70)
        self.mode_combo.setToolTip("选择对话模式")
        layout.addWidget(self.mode_combo)

        self.thinking_toggle = self._make_toggle("🧠", "显示思考过程")
        layout.addWidget(self.thinking_toggle)

        self.mcp_toggle = self._make_toggle("🔌", "启用 MCP 工具")
        layout.addWidget(self.mcp_toggle)

        self.search_toggle = self._make_toggle("🔍", "启用网络搜索")
        layout.addWidget(self.search_toggle)

        self.conv_settings_btn = self._make_button("⚙", "对话设置 (采样参数/系统提示)")
        self.conv_settings_btn.clicked.connect(self.conversation_settings_requested.emit)
        layout.addWidget(self.conv_settings_btn)

        self.provider_settings_btn = self._make_button("🔧", "配置服务商 (API/Key/模型列表)")
        self.provider_settings_btn.clicked.connect(self.provider_settings_requested.emit)
        layout.addWidget(self.provider_settings_btn)

        layout.addStretch()

        self.prompt_optimize_btn = self._make_button("✨", "优化提示词")
        self.prompt_optimize_btn.clicked.connect(self.prompt_optimize_requested.emit)
        layout.addWidget(self.prompt_optimize_btn)

        self.send_btn = self._make_button("➤", "发送消息 (Ctrl+Enter)")
        self.send_btn.clicked.connect(self.send_requested.emit)
        layout.addWidget(self.send_btn)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _make_button(self, text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("toolbar_btn")
        button.setText(text)
        button.setToolTip(tooltip)
        return button

    def _make_toggle(self, text: str, tooltip: str) -> QToolButton:
        button = self._make_button(text, tooltip)
        button.setCheckable(True)
        return button

    def set_streaming_state(self, is_streaming: bool, style) -> None:
        if is_streaming:
            try:
                self.send_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_MediaStop))
            except Exception:
                pass
            self.send_btn.setToolTip("停止生成")
            self.prompt_optimize_btn.setEnabled(False)
            self.mcp_toggle.setEnabled(False)
            self.search_toggle.setEnabled(False)
            return

        try:
            self.send_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_ArrowRight))
        except Exception:
            pass
        self.send_btn.setToolTip("发送消息 (Ctrl+Enter)")

    def set_prompt_optimize_busy(self, busy: bool, *, is_streaming: bool) -> None:
        self.prompt_optimize_btn.setEnabled((not busy) and (not is_streaming))
        self.prompt_optimize_btn.setToolTip("优化中..." if busy else "优化提示词")

class FileCompleterPopup(QListWidget):
    """Popup list for file completion"""
    
    file_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #ccc;
                border-radius: 4px;
            }
            QListWidget::item {
                padding: 4px 8px;
            }
            QListWidget::item:selected {
                background-color: #007acc;
                color: white;
            }
        """)
        self.hide()
        
    def show_completions(self, files: List[str], point):
        self.clear()
        if not files:
            self.hide()
            return
            
        self.addItems(files)
        self.setCurrentRow(0)
        
        # Calculate size
        h = min(len(files) * 26 + 4, 200)
        w = 200
        self.resize(w, h)
        self.move(point)
        self.show()
        self.raise_()

    def keyPressEvent(self, event):
        # Forward keys to parent if needed, but usually handled by event filter in TextEdit
        super().keyPressEvent(event)


class MessageTextEdit(QTextEdit):
    """Custom text edit with Ctrl+Enter and inline mention completion."""
    
    send_requested = pyqtSignal()
    attachments_received = pyqtSignal(list)
    file_reference_added = pyqtSignal(str) # Emits full path
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.work_dir: Optional[str] = None
        self._command_registry: Optional[CommandRegistry] = None
        self._mention_context_provider: Optional[Callable[[], Dict[str, Any]]] = None
        self._completion_candidates: dict[str, MentionCandidate] = {}
        self._active_query: Optional[MentionQuery] = None
        
        # Completion popup
        self.completer_popup = FileCompleterPopup(self)
        self.completer_popup.itemClicked.connect(self._on_completion_selected)
        self.completer_popup.hide()
        
        self._completing = False
        self._completion_prefix = ""
        self._completion_start_pos = -1

    def set_work_dir(self, path: str):
        self.work_dir = path

    def configure_command_registry(
        self,
        registry: CommandRegistry,
        context_provider: Callable[[], Dict[str, Any]],
    ) -> None:
        self._command_registry = registry
        self._mention_context_provider = context_provider

    def _refresh_modes(self, work_dir: str) -> None:
        try:
            cur_slug = str(self.mode_combo.currentData() or '')
        except Exception:
            cur_slug = ''

        try:
            self.mode_combo.blockSignals(True)
            self.mode_combo.clear()
            # Modes are global user configuration (APPDATA/PyChat/modes.json), not per-workspace.
            self._mode_manager = ModeManager(None)
            for m in self._mode_manager.list_modes():
                self.mode_combo.addItem(m.name, m.slug)
            if cur_slug:
                idx = self.mode_combo.findData(cur_slug)
                if idx >= 0:
                    self.mode_combo.setCurrentIndex(idx)
        finally:
            try:
                self.mode_combo.blockSignals(False)
            except Exception:
                pass

    def insertFromMimeData(self, source):
        # Handle screenshot paste / drag-drop image -> add as attachment instead of inserting into text.
        try:
            data_urls, file_paths = extract_images_from_mime(source)
            sources: list[str] = []
            sources.extend(data_urls)
            sources.extend(file_paths)
            if sources:
                self.attachments_received.emit(sources)
                return
        except Exception:
            pass

        super().insertFromMimeData(source)
    
    def keyPressEvent(self, event: QKeyEvent):
        if self.completer_popup.isVisible():
            if event.key() == Qt.Key.Key_Down:
                row = self.completer_popup.currentRow()
                if row < self.completer_popup.count() - 1:
                    self.completer_popup.setCurrentRow(row + 1)
                return
            elif event.key() == Qt.Key.Key_Up:
                row = self.completer_popup.currentRow()
                if row > 0:
                    self.completer_popup.setCurrentRow(row - 1)
                return
            elif event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab):
                if self.completer_popup.currentItem():
                    self._on_completion_selected(self.completer_popup.currentItem())
                return
            elif event.key() == Qt.Key.Key_Escape:
                self.completer_popup.hide()
                return

        if (event.key() == Qt.Key.Key_Return and 
            event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self.send_requested.emit()
            return
            
        super().keyPressEvent(event)
        
        # Check for completion trigger
        self._check_completion()

    def _check_completion(self):
        if not self._command_registry or not self._mention_context_provider:
            self.completer_popup.hide()
            return

        cursor = self.textCursor()
        result = self._command_registry.get_mention_candidates(
            self.toPlainText(),
            cursor.position(),
            self._mention_context_provider(),
        )
        if result:
            query, candidates = result
            self._show_completer(query, candidates)
            return

        self._active_query = None
        self._completion_candidates.clear()
        self.completer_popup.hide()

    def _show_completer(self, query: MentionQuery, candidates: List[MentionCandidate]):
        if not candidates:
            self.completer_popup.hide()
            return

        rect = self.cursorRect()
        point = self.viewport().mapToGlobal(rect.bottomLeft())
        point.setY(point.y() + 5)

        self._active_query = query
        self._completion_prefix = query.prefix
        self._completion_start_pos = query.start_pos
        self._completion_candidates = {candidate.label: candidate for candidate in candidates}
        self.completer_popup.show_completions([candidate.label for candidate in candidates], point)

    def _on_completion_selected(self, item):
        if not self._command_registry or not self._mention_context_provider or not self._active_query:
            return

        display_name = item.text()
        candidate = self._completion_candidates.get(display_name)
        if not display_name or candidate is None:
            return

        cursor = self.textCursor()
        cursor.setPosition(self._active_query.start_pos)
        cursor.setPosition(self._active_query.end_pos, QTextCursor.MoveMode.KeepAnchor)

        if not candidate.terminal:
            cursor.insertText(f"{self._active_query.trigger}{candidate.value}")
            self.setTextCursor(cursor)
            self.completer_popup.hide()
            self._check_completion()
            return

        if candidate.kind != MentionKind.FILE:
            insert_text = candidate.insert_text or f"{self._active_query.trigger}{candidate.value}"
            cursor.insertText(insert_text)
            self.setTextCursor(cursor)
            self.completer_popup.hide()
            self._active_query = None
            self._completion_candidates.clear()
            return

        full_path = self._command_registry.resolve_mention_candidate(
            candidate,
            self._mention_context_provider(),
        )
        if not full_path:
            self.completer_popup.hide()
            return

        cursor.removeSelectedText()
        self.setTextCursor(cursor)
        self.completer_popup.hide()
        self._active_query = None
        self._completion_candidates.clear()
        self.file_reference_added.emit(full_path)


class InputArea(QWidget):
    """Input area - single-row compact toolbar + input"""
    
    message_sent = pyqtSignal(str, list)
    slash_command_result = pyqtSignal(object)  # CommandResult from slash commands
    cancel_requested = pyqtSignal()
    conversation_settings_requested = pyqtSignal()
    provider_settings_requested = pyqtSignal()  # New: quick access to provider config
    show_thinking_changed = pyqtSignal(bool)
    mcp_toggled = pyqtSignal(bool)  # MCP 开关
    search_toggled = pyqtSignal(bool)  # 搜索开关
    prompt_optimize_requested = pyqtSignal(str)  # Optimize current input prompt
    
    provider_model_changed = pyqtSignal(str, str)  # provider_id, model

    def __init__(
        self,
        parent=None,
        *,
        command_registry: Optional[CommandRegistry] = None,
        tool_schema_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    ):
        super().__init__(parent)
        self.setObjectName("input_container")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._command_registry = command_registry or CommandRegistry()
        self._tool_schema_provider = tool_schema_provider
        self._attachments: List[Dict[str, Any]] = []  # [{'path': str, 'type': 'image'|'file'}]
        self._conversation = None
        self._providers = []
        self._suppress_thinking_signal = False
        self._suppress_tool_signals = False
        self._mcp_enabled = False
        self._search_enabled = False
        self._work_dir = ""
        self._is_streaming = False
        self._setup_ui()

    def set_work_dir(self, path: str):
        self._work_dir = path
        self.text_input.set_work_dir(path)
        try:
            self._refresh_modes(path)
        except Exception:
            pass

        # Re-apply mode policy after refresh (modes.json may change groups).
        try:
            self._apply_mode_policy(apply_defaults=False)
        except Exception:
            pass

    def _refresh_modes(self, work_dir: str) -> None:
        """Reload modes from global user config and keep selection if possible."""
        try:
            cur_slug = str(self.mode_combo.currentData() or '')
        except Exception:
            cur_slug = ''

        try:
            self.mode_combo.blockSignals(True)
            self.mode_combo.clear()
            self._mode_manager = ModeManager(None)
            for m in self._mode_manager.list_modes():
                self.mode_combo.addItem(m.name, m.slug)
            if cur_slug:
                idx = self.mode_combo.findData(cur_slug)
                if idx >= 0:
                    self.mode_combo.setCurrentIndex(idx)
        finally:
            try:
                self.mode_combo.blockSignals(False)
            except Exception:
                pass
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(3)

        self.attachment_strip = AttachmentPreviewStrip()
        self.attachment_strip.remove_requested.connect(self._remove_attachment)
        layout.addWidget(self.attachment_strip)
        
        # ===== Main input wrapper =====
        input_wrapper = QFrame()
        input_wrapper.setObjectName("input_wrapper")
        input_wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        wrapper_layout = QVBoxLayout(input_wrapper)
        wrapper_layout.setContentsMargins(4, 4, 4, 4)
        wrapper_layout.setSpacing(3)
        
        # Text input
        self.text_input = MessageTextEdit()
        self.text_input.setObjectName("message_input")
        self.text_input.setPlaceholderText("输入消息... (Ctrl+Enter 发送，#file，@tool，@mode)")
        self.text_input.setMinimumHeight(40)
        self.text_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text_input.configure_command_registry(self._command_registry, self._build_command_context)
        self.text_input.send_requested.connect(self._send_message)
        self.text_input.attachments_received.connect(self.add_attachments)
        self.text_input.file_reference_added.connect(self._add_attachment_file)
        wrapper_layout.addWidget(self.text_input)

        self.toolbar = ComposerToolbar()
        self.toolbar.attach_requested.connect(self._attach_file)
        self.toolbar.conversation_settings_requested.connect(self.conversation_settings_requested.emit)
        self.toolbar.provider_settings_requested.connect(self.provider_settings_requested.emit)
        self.toolbar.prompt_optimize_requested.connect(self._on_prompt_optimize_clicked)
        self.toolbar.send_requested.connect(self._on_send_btn_clicked)
        wrapper_layout.addWidget(self.toolbar)
        layout.addWidget(input_wrapper)

        self.provider_combo = self.toolbar.provider_combo
        self.model_combo = self.toolbar.model_combo
        self.mode_combo = self.toolbar.mode_combo
        self.thinking_toggle = self.toolbar.thinking_toggle
        self.mcp_toggle = self.toolbar.mcp_toggle
        self.search_toggle = self.toolbar.search_toggle
        self.prompt_optimize_btn = self.toolbar.prompt_optimize_btn
        self.send_btn = self.toolbar.send_btn

        self._mode_manager = ModeManager()
        for m in self._mode_manager.list_modes():
            self.mode_combo.addItem(m.name, m.slug)

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_combo.currentIndexChanged.connect(self._emit_provider_model_changed)
        self.model_combo.currentTextChanged.connect(self._emit_provider_model_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.thinking_toggle.toggled.connect(self._on_thinking_toggled)
        self.mcp_toggle.toggled.connect(self._on_mcp_toggled)
        self.search_toggle.toggled.connect(self._on_search_toggled)

        # Apply initial policy (enable/disable only) based on default mode.
        # Do not force defaults here; the current conversation/settings will sync later.
        try:
            self._apply_mode_policy(apply_defaults=False)
        except Exception:
            pass

    def _on_mode_changed(self, index: int) -> None:
        try:
            self._apply_mode_policy(apply_defaults=True)
        except Exception:
            pass

    def _apply_mode_policy(self, apply_defaults: bool = True) -> None:
        """Apply mode-derived policy to Thinking/MCP/Search toggles.

        - Disallowed toggles are disabled and forced off.
        - If apply_defaults is True, allowed toggles are set to the mode defaults.
        """
        slug = self.get_selected_mode_slug()
        mode = self._mode_manager.get(slug)
        policy = get_mode_feature_policy(mode)

        # Thinking toggle is always allowed, but can have defaults.
        if apply_defaults:
            # Apply as a real user-visible toggle change so the app state stays in sync.
            self.thinking_toggle.setChecked(bool(policy.default_thinking))

        # MCP/Search toggles: suppress signals while applying.
        self._suppress_tool_signals = True
        try:
            # MCP
            self.mcp_toggle.setEnabled(bool(policy.allow_mcp) and (not self._is_streaming))
            if not policy.allow_mcp:
                self.mcp_toggle.setChecked(False)
            elif apply_defaults:
                self.mcp_toggle.setChecked(bool(policy.default_mcp))

            # Search
            self.search_toggle.setEnabled(bool(policy.allow_search) and (not self._is_streaming))
            if not policy.allow_search:
                self.search_toggle.setChecked(False)
            elif apply_defaults:
                self.search_toggle.setChecked(bool(policy.default_search))

            self._mcp_enabled = bool(self.mcp_toggle.isChecked())
            self._search_enabled = bool(self.search_toggle.isChecked())
        finally:
            self._suppress_tool_signals = False
    def set_streaming_state(self, is_streaming: bool):
        self._is_streaming = is_streaming
        self.toolbar.set_streaming_state(is_streaming, self.style())
        if is_streaming:
            self.text_input.setEnabled(False)
        else:
            self.text_input.setEnabled(True)
            self.text_input.setFocus()
            try:
                self._apply_mode_policy(apply_defaults=False)
            except Exception:
                pass


    def set_prompt_optimize_busy(self, busy: bool) -> None:
        self.toolbar.set_prompt_optimize_busy(busy, is_streaming=self._is_streaming)

    def _on_prompt_optimize_clicked(self) -> None:
        try:
            text = (self.text_input.toPlainText() or "").strip()
        except Exception:
            text = ""
        if not text:
            return
        try:
            self.set_prompt_optimize_busy(True)
        except Exception:
            pass
        self.prompt_optimize_requested.emit(text)

    def _on_send_btn_clicked(self):
        if self._is_streaming:
            self.cancel_requested.emit()
        else:
            self._send_message()

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

        self._emit_provider_model_changed()
    
    def _emit_provider_model_changed(self) -> None:
        try:
            provider_id = self.get_selected_provider_id()
            model = (self.get_selected_model() or "").strip()
        except Exception:
            return
        self.provider_model_changed.emit(provider_id, model)

    def get_selected_provider_id(self) -> str:
        return self.provider_combo.currentData() or ""
    
    def get_selected_model(self) -> str:
        return self.model_combo.currentText()

    def get_selected_mode(self) -> str:
        return self.mode_combo.currentText()

    def get_selected_mode_slug(self) -> str:
        try:
            return str(self.mode_combo.currentData() or '').strip() or (self.get_selected_mode() or '').strip().lower()
        except Exception:
            return (self.get_selected_mode() or '').strip().lower()

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
    
    def _on_mcp_toggled(self, checked: bool):
        if self._suppress_tool_signals:
            self._mcp_enabled = bool(checked)
            return
        self._mcp_enabled = bool(checked)
        self.mcp_toggled.emit(bool(checked))
    
    def _on_search_toggled(self, checked: bool):
        if self._suppress_tool_signals:
            self._search_enabled = bool(checked)
            return
        self._search_enabled = bool(checked)
        self.search_toggled.emit(bool(checked))
    
    def is_mcp_enabled(self) -> bool:
        return self._mcp_enabled
    
    def is_search_enabled(self) -> bool:
        return self._search_enabled

    def get_effective_tool_flags(self) -> tuple[bool, bool]:
        """Return (enable_search, enable_mcp) clamped by current mode policy."""
        try:
            slug = self.get_selected_mode_slug()
            mode = self._mode_manager.get(slug)
            policy = get_mode_feature_policy(mode)
            _t, mcp, search = clamp_feature_flags(
                policy,
                enable_thinking=bool(self.thinking_toggle.isChecked()),
                enable_mcp=bool(self._mcp_enabled),
                enable_search=bool(self._search_enabled),
            )
            return bool(search), bool(mcp)
        except Exception:
            return bool(self._search_enabled), bool(self._mcp_enabled)

    def build_run_policy(self, *, enable_thinking: Optional[bool] = None, retry_config=None) -> RunPolicy:
        """Build RunPolicy based on selected mode + current toggles.

        Note: The core mapping lives in `core.task.builder.build_run_policy`
        (pure core, reusable by future TUI). This method only reads UI state.
        """

        try:
            slug = self.get_selected_mode_slug()
        except Exception:
            slug = "chat"

        # Tool flags are clamped by mode feature policy.
        enable_search, enable_mcp = self.get_effective_tool_flags()

        if enable_thinking is None:
            try:
                enable_thinking = bool(self.thinking_toggle.isChecked())
            except Exception:
                enable_thinking = True

        return build_run_policy(
            mode_slug=str(slug or "chat"),
            enable_thinking=bool(enable_thinking),
            enable_search=bool(enable_search),
            enable_mcp=bool(enable_mcp),
            mode_manager=getattr(self, "_mode_manager", None),
            retry_config=retry_config,
        )

    def apply_mode_policy(self, apply_defaults: bool = False) -> None:
        """Public wrapper for applying mode policy.

        Use apply_defaults=False when syncing UI from stored conversation settings.
        """
        self._apply_mode_policy(apply_defaults=apply_defaults)
    
    def _attach_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, '添加文件', '',
            '所有文件 (*);;图片 (*.png *.jpg *.jpeg *.gif *.webp)'
        )
        for file_path in file_paths:
            self._add_attachment_file(file_path)

    def add_attachments(self, sources: list) -> None:
        if not sources:
            return
        for src in sources:
            if isinstance(src, str) and src:
                self._add_attachment_file(src)

        try:
            self.text_input.setFocus()
        except Exception:
            pass

    def _add_attachment_file(self, path: str):
        # Check if already attached
        for att in self._attachments:
            if att['path'] == path:
                return
        
        is_img = False
        if path.startswith("data:image"):
            is_img = True
        elif is_supported_image_path(path):
            is_img = True
            
        self._attachments.append({'path': path, 'type': 'image' if is_img else 'file'})
        self.attachment_strip.add_attachment(path, is_image=is_img)

    def _remove_attachment(self, path: str):
        for i, att in enumerate(self._attachments):
            if att['path'] == path:
                self._attachments.pop(i)
                break

        self.attachment_strip.remove_attachment(path)

    def set_conversation(self, conversation) -> None:
        """Set the current conversation for command context."""
        self._conversation = conversation

    def _build_command_context(self) -> Dict[str, Any]:
        try:
            available_tools = self._tool_schema_provider() if self._tool_schema_provider else []
        except Exception:
            available_tools = []

        return {
            "current_mode": self.get_selected_mode_slug(),
            "conversation": self._conversation,
            "work_dir": self._work_dir,
            "available_tools": available_tools,
            "available_modes": [
                {"slug": mode.slug, "name": mode.name}
                for mode in self._mode_manager.list_modes()
            ],
        }

    def _try_handle_slash_command(self, content: str) -> bool:
        if not self._command_registry.is_slash_command(content):
            return False

        result = self._command_registry.execute(content, self._build_command_context())
        if result is None:
            return False

        self.text_input.clear()
        self.slash_command_result.emit(result)
        return True

    def _emit_message_payload(self, content: str) -> None:
        from core.attachments import process_attachments

        result = process_attachments(self._attachments)
        if result.file_content_suffix:
            content += result.file_content_suffix
        self.message_sent.emit(content, result.encoded_images)

    def _clear_composer(self) -> None:
        self.text_input.clear()
        self._attachments.clear()
        self.attachment_strip.clear_attachments()

    def _send_message(self):
        content = self.text_input.toPlainText().strip()

        if content.startswith("/") and self._try_handle_slash_command(content):
            return

        if not content and not self._attachments:
            self.message_sent.emit("", [])
            return

        self._emit_message_payload(content)
        self._clear_composer()
    
    def set_enabled(self, enabled: bool):
        self.text_input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        data_urls, file_paths = extract_images_from_mime(event.mimeData())
        self.add_attachments(data_urls + file_paths)
