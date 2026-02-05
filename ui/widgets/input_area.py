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
import base64
import os
from typing import List, Dict, Any, Optional

from core.agent.modes import ModeManager
from core.agent.modes.policy import get_mode_feature_policy, clamp_feature_flags
from core.agent.policy import RunPolicy
from core.agent.policy_builder import build_run_policy

from ui.utils.image_loader import load_pixmap
from ui.utils.image_utils import extract_images_from_mime, is_supported_image_path


class AttachmentPreviewItem(QFrame):
    """Preview item for attached images or files"""
    
    remove_requested = pyqtSignal(str)
    
    def __init__(self, source: str, is_image: bool = True, parent=None):
        super().__init__(parent)
        self.source = source
        self.is_image = is_image
        self._setup_ui()
    
    def _setup_ui(self):
        self.setObjectName("image_preview_item")
        self.setFixedSize(60, 56)  # Slightly wider for file names
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)
        
        thumb = QLabel()
        thumb.setObjectName("image_thumb")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        if self.is_image:
            pixmap = load_pixmap(self.source)
            if not pixmap.isNull():
                scaled = pixmap.scaled(56, 38, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                thumb.setPixmap(scaled)
            else:
                thumb.setText("IMG")
        else:
            # File icon/text
            ext = os.path.splitext(self.source)[1].lower() or "FILE"
            thumb.setText(ext)
            thumb.setStyleSheet("font-size: 10px; font-weight: bold; color: #555;")
            thumb.setToolTip(os.path.basename(self.source))

        layout.addWidget(thumb)
        
        # Add filename label for non-images
        if not self.is_image:
            name_lbl = QLabel(os.path.basename(self.source))
            name_lbl.setObjectName("file_name_lbl")
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet("font-size: 9px; color: #666;")
            # Elide text
            font_metrics = name_lbl.fontMetrics()
            elided = font_metrics.elidedText(name_lbl.text(), Qt.TextElideMode.ElideMiddle, 56)
            name_lbl.setText(elided)
            layout.addWidget(name_lbl)

        
        remove_btn = QPushButton("×")
        remove_btn.setObjectName("image_remove_btn")
        remove_btn.setFixedSize(14, 14)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.source))
        
        # Position remove button at top-right absolutely
        remove_btn.setParent(self)
        remove_btn.move(self.width() - 16, 2)
        remove_btn.show()


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
    """Custom text edit with Ctrl+Enter to send and # file completion"""
    
    send_requested = pyqtSignal()
    attachments_received = pyqtSignal(list)
    file_reference_added = pyqtSignal(str) # Emits full path
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.work_dir: Optional[str] = None
        
        # Completion popup
        self.completer_popup = FileCompleterPopup(self)
        self.completer_popup.itemClicked.connect(self._on_completion_selected)
        self.completer_popup.hide()
        
        self._completing = False
        self._completion_prefix = ""
        self._completion_start_pos = -1

    def set_work_dir(self, path: str):
        self.work_dir = path

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
        cursor = self.textCursor()
        text = self.toPlainText()
        pos = cursor.position()
        
        # Look backwards for '#'
        # Simple heuristic: find last '#' before cursor that is not preceded by non-space
        # (Actually, strict '#name' is fine)
        
        line_start = text.rfind('\n', 0, pos) + 1
        current_line_text = text[line_start:pos]
        
        hash_idx = current_line_text.rfind('#')
        if hash_idx != -1:
            # Check if it's a valid trigger (start of line or preceded by space)
            if hash_idx == 0 or current_line_text[hash_idx-1].isspace():
                prefix = current_line_text[hash_idx+1:]
                self._show_completer(prefix, pos - len(prefix))
                return
        
        self.completer_popup.hide()

    def _show_completer(self, prefix: str, global_pos: int):
        if not self.work_dir or not os.path.isdir(self.work_dir):
            self.completer_popup.hide()
            return
            
        try:
            files = [f for f in os.listdir(self.work_dir) 
                     if os.path.isfile(os.path.join(self.work_dir, f)) 
                     and not f.startswith('.')
                     and prefix.lower() in f.lower()]
        except Exception:
            files = []
            
        if not files:
            self.completer_popup.hide()
            return
            
        rect = self.cursorRect()
        # Map to global coordinates then to popup parent (which is this widget, so just widget coords)
        # Actually QListWidget is child of TextEdit, so simple mapToGlobal not needed if move(local)
        # But we want it to float. 
        # Better: map to global, then map to parent of popup if popup was window.
        # Here popup is child of TextEdit.
        # Let's adjust position.
        
        point = self.viewport().mapToGlobal(rect.bottomLeft())
        point.setY(point.y() + 5)
        
        self._completion_prefix = prefix
        self._completion_start_pos = global_pos
        self.completer_popup.show_completions(files, point)

    def _on_completion_selected(self, item):
        filename = item.text()
        if not filename or not self.work_dir:
            return
            
        full_path = os.path.join(self.work_dir, filename)
        
        # Replace the #text with nothing (since we add it as attachment)
        # Or replace with [File: name]
        
        cursor = self.textCursor()
        # We need to delete back to '#'
        # Position is current cursor. 
        # We know prefix length.
        prefix_len = len(self._completion_prefix)
        
        # Select from (end) back to (start - 1 for hash)
        # Wait, cursor is at end of prefix.
        
        # Move cursor to end of prefix if not already (it should be)
        # Select previous (prefix_len + 1) characters
        for _ in range(prefix_len + 1):
            cursor.deletePreviousChar()
            
        self.setTextCursor(cursor)
        self.completer_popup.hide()
        
        self.file_reference_added.emit(full_path)


class InputArea(QWidget):
    """Input area - single-row compact toolbar + input"""
    
    message_sent = pyqtSignal(str, list)
    cancel_requested = pyqtSignal()
    conversation_settings_requested = pyqtSignal()
    provider_settings_requested = pyqtSignal()  # New: quick access to provider config
    show_thinking_changed = pyqtSignal(bool)
    mcp_toggled = pyqtSignal(bool)  # MCP 开关
    search_toggled = pyqtSignal(bool)  # 搜索开关
    prompt_optimize_requested = pyqtSignal(str)  # Optimize current input prompt
    
    provider_model_changed = pyqtSignal(str, str)  # provider_id, model
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("input_container")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._attachments: List[Dict[str, Any]] = []  # [{'path': str, 'type': 'image'|'file'}]
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
        
        # Image preview (hidden by default)
        self.image_preview = QWidget()
        self.image_preview.setObjectName("image_preview")
        self.image_layout = QHBoxLayout(self.image_preview)
        self.image_layout.setContentsMargins(4, 0, 4, 0)
        self.image_layout.setSpacing(4)
        self.image_layout.addStretch()
        self.image_preview.setVisible(False)
        layout.addWidget(self.image_preview)
        
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
        self.text_input.setPlaceholderText("输入消息... (Ctrl+Enter 发送，# 引用当前文件夹文件)")
        self.text_input.setMinimumHeight(40)
        # self.text_input.setMaximumHeight(120)  # Removed to allow expansion in splitter
        self.text_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text_input.send_requested.connect(self._send_message)
        self.text_input.attachments_received.connect(self.add_attachments)
        self.text_input.file_reference_added.connect(self._add_attachment_file)
        wrapper_layout.addWidget(self.text_input)
        
        # ===== Single-row toolbar: [📎] [Provider▾] [Model▾] [🧠] [⚙] [🔧] --- [发送] =====
        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)
        
        # Attach button
        self.attach_btn = QToolButton()
        self.attach_btn.setObjectName("toolbar_btn")
        self.attach_btn.setText("📎")
        self.attach_btn.setToolTip("添加文件/图片")
        self.attach_btn.clicked.connect(self._attach_file)
        toolbar.addWidget(self.attach_btn)
        
        # Provider selector
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("provider_combo")
        self.provider_combo.setMinimumWidth(70)
        self.provider_combo.setMaximumWidth(110)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_combo.currentIndexChanged.connect(self._emit_provider_model_changed)
        toolbar.addWidget(self.provider_combo)
        
        # Model selector
        self.model_combo = QComboBox()
        self.model_combo.setObjectName("model_combo")
        self.model_combo.setMinimumWidth(120)
        self.model_combo.setMaximumWidth(200)
        self.model_combo.setEditable(True)
        self.model_combo.currentTextChanged.connect(self._emit_provider_model_changed)
        toolbar.addWidget(self.model_combo)

        # Mode selector
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("mode_combo")
        # Populate modes from ModeManager
        self._mode_manager = ModeManager()
        for m in self._mode_manager.list_modes():
            self.mode_combo.addItem(m.name, m.slug)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_combo.setToolTip("选择对话模式")
        self.mode_combo.setMinimumWidth(70)
        toolbar.addWidget(self.mode_combo)
        
        # Thinking toggle
        self.thinking_toggle = QToolButton()
        self.thinking_toggle.setObjectName("toolbar_btn")
        self.thinking_toggle.setText("🧠")
        self.thinking_toggle.setToolTip("显示思考过程")
        self.thinking_toggle.setCheckable(True)
        self.thinking_toggle.toggled.connect(self._on_thinking_toggled)
        toolbar.addWidget(self.thinking_toggle)
        
        # MCP toggle
        self.mcp_toggle = QToolButton()
        self.mcp_toggle.setObjectName("toolbar_btn")
        self.mcp_toggle.setText("🔌")
        self.mcp_toggle.setToolTip("启用 MCP 工具")
        self.mcp_toggle.setCheckable(True)
        self.mcp_toggle.toggled.connect(self._on_mcp_toggled)
        toolbar.addWidget(self.mcp_toggle)
        
        # Search toggle
        self.search_toggle = QToolButton()
        self.search_toggle.setObjectName("toolbar_btn")
        self.search_toggle.setText("🔍")
        self.search_toggle.setToolTip("启用网络搜索")
        self.search_toggle.setCheckable(True)
        self.search_toggle.toggled.connect(self._on_search_toggled)
        toolbar.addWidget(self.search_toggle)
        
        # Conversation settings
        self.conv_settings_btn = QToolButton()
        self.conv_settings_btn.setObjectName("toolbar_btn")
        self.conv_settings_btn.setText("⚙")
        self.conv_settings_btn.setToolTip("对话设置 (采样参数/系统提示)")
        self.conv_settings_btn.clicked.connect(self.conversation_settings_requested.emit)
        toolbar.addWidget(self.conv_settings_btn)
        
        # Provider settings (quick access)
        self.provider_settings_btn = QToolButton()
        self.provider_settings_btn.setObjectName("toolbar_btn")
        self.provider_settings_btn.setText("🔧")
        self.provider_settings_btn.setToolTip("配置服务商 (API/Key/模型列表)")
        self.provider_settings_btn.clicked.connect(self.provider_settings_requested.emit)
        toolbar.addWidget(self.provider_settings_btn)
        
        toolbar.addStretch()
        # Prompt optimize button (icon)
        self.prompt_optimize_btn = QToolButton()
        self.prompt_optimize_btn.setObjectName("toolbar_btn")
        self.prompt_optimize_btn.setText("✨")
        # self.prompt_optimize_btn.setFixedSize(30, 28)
        self.prompt_optimize_btn.setToolTip("优化提示词")
        self.prompt_optimize_btn.clicked.connect(self._on_prompt_optimize_clicked)
        toolbar.addWidget(self.prompt_optimize_btn)
        # Send button (icon)
        self.send_btn = QToolButton()
        self.send_btn.setObjectName("toolbar_btn")
        # self.send_btn.setText("➡") 
        # self.send_btn.setText("⬆")
        self.send_btn.setText("➤")
        # self.send_btn.setFixedSize(34, 28)
        self.send_btn.setToolTip("发送消息 (Ctrl+Enter)")
        self.send_btn.clicked.connect(self._on_send_btn_clicked)
        toolbar.addWidget(self.send_btn)
        
        wrapper_layout.addLayout(toolbar)
        layout.addWidget(input_wrapper)

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
        if is_streaming:
            try:
                self.send_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
            except Exception:
                pass
            self.send_btn.setToolTip("停止生成")
            self.text_input.setEnabled(False)
            try:
                self.prompt_optimize_btn.setEnabled(False)
            except Exception:
                pass
            try:
                # Streaming disables tool toggles (policy still applies)
                self.mcp_toggle.setEnabled(False)
                self.search_toggle.setEnabled(False)
            except Exception:
                pass
        else:
            try:
                self.send_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
            except Exception:
                pass
            self.send_btn.setToolTip("发送消息 (Ctrl+Enter)")
            self.text_input.setEnabled(True)
            self.text_input.setFocus()
            try:
                # only re-enable if not busy
                self.prompt_optimize_btn.setEnabled(True)
            except Exception:
                pass
            try:
                self._apply_mode_policy(apply_defaults=False)
            except Exception:
                pass


    def set_prompt_optimize_busy(self, busy: bool) -> None:
        try:
            self.prompt_optimize_btn.setEnabled((not busy) and (not self._is_streaming))
            self.prompt_optimize_btn.setToolTip("优化中..." if busy else "优化提示词")
        except Exception:
            pass

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

    def build_run_policy(self, *, enable_thinking: Optional[bool] = None) -> RunPolicy:
        """Build RunPolicy based on selected mode + current toggles.

        Note: The core mapping lives in `core.agent.policy_builder.build_run_policy`
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
        
        preview = AttachmentPreviewItem(path, is_image=is_img)
        preview.remove_requested.connect(self._remove_attachment)
        self.image_layout.insertWidget(self.image_layout.count() - 1, preview)
        self.image_preview.setVisible(True)

    def _remove_attachment(self, path: str):
        for i, att in enumerate(self._attachments):
            if att['path'] == path:
                self._attachments.pop(i)
                break
        
        for i in range(self.image_layout.count()):
            item = self.image_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, AttachmentPreviewItem) and widget.source == path:
                widget.deleteLater()
                break
        
        if not self._attachments:
            self.image_preview.setVisible(False)

    def _send_message(self):
        content = self.text_input.toPlainText().strip()

        # Allow sending if we have attachments
        if not content and not self._attachments:
            self.message_sent.emit("", [])
            return
        
        encoded_images = []
        file_contents = []
        
        for att in self._attachments:
            path = att['path']
            atype = att['type']
            
            if atype == 'image':
                try:
                    if isinstance(path, str) and path.startswith('data:'):
                        encoded_images.append(path)
                        continue

                    with open(path, 'rb') as f:
                        data = base64.b64encode(f.read()).decode('utf-8')
                    ext = os.path.splitext(path)[1].lower()
                    mime = {'.png': 'image/png', '.jpg': 'image/jpeg',
                            '.jpeg': 'image/jpeg', '.gif': 'image/gif',
                            '.webp': 'image/webp', '.bmp': 'image/bmp'}.get(ext, 'image/png')
                    encoded_images.append(f"data:{mime};base64,{data}")
                except Exception as e:
                    print(f"Error loading image {path}: {e}")
            else:
                # Text/Other file
                try:
                    # Check size limit? e.g. 1MB for now
                    if os.path.getsize(path) > 1024 * 1024:
                        print(f"File too large: {path}")
                        # Maybe add a warning note?
                        file_contents.append(f"\n[File: {os.path.basename(path)} (Skipped: >1MB)]\n")
                        continue
                        
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            text = f.read()
                        file_contents.append(f"\n\n--- File: {os.path.basename(path)} ---\n{text}\n--- End File ---")
                    except UnicodeDecodeError:
                        file_contents.append(f"\n[File: {os.path.basename(path)} (Binary content)]\n")
                except Exception as e:
                    print(f"Error reading file {path}: {e}")
        
        # Append file contents to message
        if file_contents:
            content += "".join(file_contents)

        self.message_sent.emit(content, encoded_images)
        
        self.text_input.clear()
        self._attachments.clear()
        while self.image_layout.count() > 1:
            item = self.image_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.image_preview.setVisible(False)
    
    def set_enabled(self, enabled: bool):
        self.text_input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        data_urls, file_paths = extract_images_from_mime(event.mimeData())
        self.add_images(data_urls + file_paths)
