"""
Main application window - Chinese UI with fixed streaming
"""

import os
import uuid
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from typing import Optional

from models.conversation import Conversation, Message
from models.provider import Provider
from services.storage_service import StorageService
from core.llm.client import LLMClient
from services.provider_service import ProviderService
from core.tools.manager import McpManager
from ui.runtime.message_runtime import MessageRuntime
from ui.runtime.prompt_optimizer_runtime import PromptOptimizer

from .widgets.sidebar import Sidebar
from .widgets.chat_view import ChatView
from .widgets.input_area import InputArea
from .widgets.stats_panel import StatsPanel

from core.state.services.task_service import TaskService
from .settings.settings_dialog import SettingsDialog
from .dialogs.message_editor import MessageEditorDialog
from .dialogs.conversation_settings_dialog import ConversationSettingsDialog


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        self.storage = StorageService()
        self.client = LLMClient()
        self.provider_service = ProviderService()
        self.mcp_manager = McpManager()
        self.message_runtime = MessageRuntime(self.client, mcp_manager=self.mcp_manager, parent=self)
        
        self.providers: list[Provider] = []
        self.current_conversation: Optional[Conversation] = None
        self._app_settings: dict = {}
        self._syncing_input_selection: bool = False

        # Streaming events (thread-safe; runtime normalizes + guards request_id)
        self.message_runtime.token_received.connect(self._on_token_received)
        self.message_runtime.thinking_received.connect(self._on_thinking_received)
        self.message_runtime.response_step.connect(self._on_response_step)
        self.message_runtime.response_complete.connect(self._on_response_complete)
        self.message_runtime.response_error.connect(self._on_response_error)

        self.prompt_optimizer = PromptOptimizer(self.client, parent=self)
        self.prompt_optimizer.optimize_started.connect(self._on_prompt_optimize_started)
        self.prompt_optimizer.optimize_complete.connect(self._on_prompt_optimize_complete)
        self.prompt_optimizer.optimize_error.connect(self._on_prompt_optimize_error)
        
        self._setup_ui()
        self._load_data()
        self._apply_theme()
    
    def _setup_ui(self):
        self.setWindowTitle("PyChat - LLM 会话管理")
        self.setMinimumSize(1000, 600)
        
        central = QWidget()
        central.setObjectName("central_widget")
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(central)
        
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Sidebar
        self.sidebar = Sidebar()
        self.sidebar.conversation_selected.connect(self._on_conversation_selected)
        self.sidebar.new_conversation.connect(self._new_conversation)
        self.sidebar.import_conversation.connect(self._import_conversation)
        self.sidebar.delete_conversation.connect(self._delete_conversation)
        self.sidebar.duplicate_conversation.connect(self._duplicate_conversation)
        
        # Chat area
        chat_widget = QWidget()
        chat_widget.setObjectName("chat_container")
        chat_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        
        self.chat_view = ChatView()
        self.chat_view.edit_message.connect(self._edit_message)
        self.chat_view.delete_message.connect(self._delete_message)
        self.chat_view.images_dropped.connect(self._on_images_dropped)
        self.chat_view.work_dir_changed.connect(self._on_work_dir_changed)
        
        self.input_area = InputArea()
        self.input_area.message_sent.connect(self._send_message)
        self.input_area.cancel_requested.connect(self._cancel_generation)
        self.input_area.conversation_settings_requested.connect(self._open_conversation_settings)
        self.input_area.provider_settings_requested.connect(self._open_provider_settings)
        self.input_area.show_thinking_changed.connect(self._on_conversation_show_thinking_changed)
        self.input_area.prompt_optimize_requested.connect(self._on_prompt_optimize_requested)
        self.input_area.provider_model_changed.connect(self._on_input_provider_model_changed)

        # Vertical splitter: message area <-> input area (user-resizable)
        self.chat_splitter = QSplitter(Qt.Orientation.Vertical)
        self.chat_splitter.setObjectName("chat_splitter")
        self.chat_splitter.setChildrenCollapsible(False)
        self.chat_splitter.setHandleWidth(8)
        self.chat_splitter.addWidget(self.chat_view)
        self.chat_splitter.addWidget(self.input_area)
        self.chat_splitter.setSizes([720, 180])
        self.chat_splitter.splitterMoved.connect(self._on_chat_splitter_moved)

        chat_layout.addWidget(self.chat_splitter, stretch=1)

        # Stats panel
        self.stats_panel = StatsPanel()
        self.stats_panel.task_create_requested.connect(self._on_task_create_requested)
        self.stats_panel.task_complete_requested.connect(self._on_task_complete_requested)
        self.stats_panel.task_delete_requested.connect(self._on_task_delete_requested)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("main_splitter")
        self.splitter.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(chat_widget)
        self.splitter.addWidget(self.stats_panel)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.setSizes([180, 760, 200])
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        main_layout.addWidget(self.splitter)
        self._create_menu_bar()

    def _on_images_dropped(self, image_sources: list) -> None:
        # Forward images dropped onto the chat area into the input area's attachments.
        try:
            self.input_area.add_images(image_sources)
        except Exception:
            pass
    
    def _create_menu_bar(self):
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("文件")
        
        new_action = QAction("新建会话", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_conversation)
        file_menu.addAction(new_action)
        
        import_action = QAction("导入 JSON...", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(lambda: self.sidebar._import_conversation())
        file_menu.addAction(import_action)
        
        file_menu.addSeparator()
        
        settings_action = QAction("设置...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        edit_menu = menubar.addMenu("编辑")
        
        cancel_action = QAction("取消生成", self)
        cancel_action.setShortcut("Escape")
        cancel_action.triggered.connect(self._cancel_generation)
        edit_menu.addAction(cancel_action)
        
        view_menu = menubar.addMenu("视图")
        
        self.toggle_stats_action = QAction("显示统计", self)
        self.toggle_stats_action.setCheckable(True)
        self.toggle_stats_action.setChecked(True)
        self.toggle_stats_action.triggered.connect(self._toggle_stats_panel)
        view_menu.addAction(self.toggle_stats_action)
        
        help_menu = menubar.addMenu("帮助")
        
        about_action = QAction("关于 PyChat", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
    
    def _load_data(self):
        self._app_settings = self.storage.load_settings() or {}
        self.mcp_manager.update_permissions(self._app_settings)
        self._apply_proxy()

        self.providers = self.storage.load_providers()
        if not self.providers:
            self.providers = self.provider_service.create_default_providers()
            self.storage.save_providers(self.providers)
        
        self.input_area.set_providers(self.providers)
        
        conversations = self.storage.list_conversations()
        self.sidebar.update_conversations(conversations)

        # Apply appearance settings that don't depend on QSS
        show_stats = bool(self._app_settings.get('show_stats', True))
        self.stats_panel.setVisible(show_stats)
        self.toggle_stats_action.setChecked(show_stats)

        # Restore splitter sizes (sidebar/chat/stats)
        sizes = self._app_settings.get('splitter_sizes')
        if isinstance(sizes, list) and len(sizes) == 3 and all(isinstance(x, int) for x in sizes):
            try:
                self.splitter.setSizes(sizes)
            except Exception:
                pass

        # Restore chat splitter sizes (messages/input)
        chat_sizes = self._app_settings.get('chat_splitter_sizes')
        if isinstance(chat_sizes, list) and len(chat_sizes) == 2 and all(isinstance(x, int) for x in chat_sizes):
            try:
                self.chat_splitter.setSizes(chat_sizes)
            except Exception:
                pass

    def _on_splitter_moved(self, pos: int, index: int):
        # Persist user layout immediately
        try:
            self._app_settings['splitter_sizes'] = [int(x) for x in self.splitter.sizes()]
            self.storage.save_settings(self._app_settings)
        except Exception:
            pass

    def _on_chat_splitter_moved(self, pos: int, index: int):
        try:
            self._app_settings['chat_splitter_sizes'] = [int(x) for x in self.chat_splitter.sizes()]
            self.storage.save_settings(self._app_settings)
        except Exception:
            pass

    def _sync_input_enabled(self) -> None:
        """Enable/disable input for the currently selected conversation only."""
        try:
            if not self.current_conversation:
                self.input_area.set_streaming_state(False)
                return
            is_streaming = self.message_runtime.is_streaming(self.current_conversation.id)
            self.input_area.set_streaming_state(is_streaming)
        except Exception:
            pass
    
    def _apply_theme(self):
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            theme = (self._app_settings.get('theme') or 'dark').lower()
            theme_file = 'light_theme.qss' if theme == 'light' else 'dark_theme.qss'
            theme_path = os.path.join(base_dir, 'assets', 'styles', theme_file)
            base_theme_path = os.path.join(base_dir, 'assets', 'styles', 'base.qss')
            
            parts: list[str] = []
            if os.path.exists(base_theme_path):
                with open(base_theme_path, 'r', encoding='utf-8') as f:
                    parts.append(f.read())
            if os.path.exists(theme_path):
                with open(theme_path, 'r', encoding='utf-8') as f:
                    parts.append(f.read())

            if parts:
                self.setStyleSheet("\n\n".join(parts))
        except Exception as e:
            print(f"Error loading theme: {e}")

    def _apply_proxy(self):
        """Update environment variables for HTTP proxy"""
        proxy = self._app_settings.get('proxy_url', '').strip()
        if proxy:
            os.environ['HTTP_PROXY'] = proxy
            os.environ['HTTPS_PROXY'] = proxy
        else:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)
    
    def _on_conversation_selected(self, conversation_id: str):
        conversation = self.storage.load_conversation(conversation_id)
        if not conversation:
            return

        self._syncing_input_selection = True
        try:
            self.current_conversation = conversation
            self.chat_view.load_conversation(conversation)
            self.stats_panel.update_stats(conversation)

            # Sync per-conversation toggles
            show_thinking_default = bool(self._app_settings.get('show_thinking', True))
            show_thinking = bool((conversation.settings or {}).get('show_thinking', show_thinking_default))
            self.input_area.set_show_thinking(show_thinking)

            # Sync provider first (so model list is populated), then sync model.
            provider_name = ""
            if conversation.provider_id:
                for i, provider in enumerate(self.providers):
                    if provider.id == conversation.provider_id:
                        self.input_area.provider_combo.setCurrentIndex(i)
                        provider_name = provider.name
                        break

            if conversation.model:
                self.input_area.model_combo.setCurrentText(conversation.model)

            # Sync mode selection
            try:
                mode_slug = str(getattr(conversation, 'mode', '') or '')
                idx = self.input_area.mode_combo.findData(mode_slug)
                if idx >= 0:
                    self.input_area.mode_combo.blockSignals(True)
                    try:
                        self.input_area.mode_combo.setCurrentIndex(idx)
                    finally:
                        self.input_area.mode_combo.blockSignals(False)
                    try:
                        self.input_area.apply_mode_policy(apply_defaults=False)
                    except Exception:
                        pass
            except Exception:
                pass

            # Update chat header
            self.chat_view.update_header(
                provider_name=provider_name,
                model=conversation.model or "",
                msg_count=len(conversation.messages)
            )
            work_dir = getattr(conversation, 'work_dir', "")
            self.chat_view.update_work_dir(work_dir)
            self.input_area.set_work_dir(work_dir)

            # Restore streaming UI if this conversation is currently generating.
            stream_state = self.message_runtime.get_state(conversation.id)
            if stream_state:
                self.chat_view.start_streaming_response(model=stream_state.model)
                self.chat_view.restore_streaming_state(
                    visible_text=stream_state.visible_text,
                    thinking_text=stream_state.thinking_text
                )

            self._sync_input_enabled()
        finally:
            self._syncing_input_selection = False

    def _new_conversation(self):
        self.current_conversation = Conversation()
        self.chat_view.clear()
        self.stats_panel.update_stats(None)
        self.chat_view.update_header(provider_name="", model="", msg_count=0)
        self.chat_view.update_work_dir("")
        self.input_area.set_work_dir("")
        self._sync_input_enabled()

    def _apply_task_ops(self, ops: list[dict]) -> None:
        if not self.current_conversation:
            return
        try:
            current_seq = self.current_conversation.next_seq_id()
            state = self.current_conversation.get_state()
            TaskService.handle_ops(state, ops, current_seq)
            state.last_updated_seq = current_seq
            self.current_conversation.set_state(state)
            self.storage.save_conversation(self.current_conversation)
        except Exception:
            return

        try:
            self.stats_panel.update_stats(self.current_conversation)
        except Exception:
            pass

    def _on_task_create_requested(self, content: str) -> None:
        text = (content or "").strip()
        if not text:
            return
        self._apply_task_ops([{"action": "create", "content": text}])

    def _on_task_complete_requested(self, task_id: str) -> None:
        tid = (task_id or "").strip()
        if not tid:
            return
        self._apply_task_ops([{"action": "update", "id": tid, "status": "completed"}])

    def _on_task_delete_requested(self, task_id: str) -> None:
        tid = (task_id or "").strip()
        if not tid:
            return
        self._apply_task_ops([{"action": "delete", "id": tid}])

    def _on_input_provider_model_changed(self, provider_id: str, model: str) -> None:
        if bool(getattr(self, '_syncing_input_selection', False)):
            return
        provider_name = ''
        try:
            for p in getattr(self, 'providers', []) or []:
                if getattr(p, 'id', '') == provider_id:
                    provider_name = getattr(p, 'name', '') or ''
                    break
        except Exception:
            provider_name = ''

        msg_count = 0
        if self.current_conversation:
            try:
                msg_count = len(self.current_conversation.messages)
            except Exception:
                msg_count = 0

        try:
            self.chat_view.update_header(provider_name=provider_name, model=(model or ''), msg_count=msg_count)
        except Exception:
            pass

        if not self.current_conversation:
            return

        # Keep in-memory conversation selection consistent; persist only if the conversation already has content.
        try:
            if provider_id:
                self.current_conversation.provider_id = provider_id
            if isinstance(model, str):
                self.current_conversation.model = model.strip()
        except Exception:
            pass

        try:
            self.stats_panel.update_stats(self.current_conversation)
        except Exception:
            pass

        try:
            if getattr(self.current_conversation, 'messages', None):
                self.storage.save_conversation(self.current_conversation)
        except Exception:
            pass

    def _on_work_dir_changed(self, path: str):
        """Handle workspace directory change"""
        if self.current_conversation:
            self.current_conversation.work_dir = path
            self.input_area.set_work_dir(path)
            self.storage.save_conversation(self.current_conversation)
            # Maybe show a toast or status bar message?
    
    def _import_conversation(self, file_path: str):
        conversation = self.storage.import_conversation(file_path)
        if conversation:
            conversations = self.storage.list_conversations()
            self.sidebar.update_conversations(conversations)
            self.sidebar.select_conversation(conversation.id)
            self._on_conversation_selected(conversation.id)
            QMessageBox.information(self, "导入成功", f"已导入会话: {conversation.title}")
        else:
            QMessageBox.warning(self, "导入失败", "无法导入会话，请检查 JSON 格式")
    
    def _delete_conversation(self, conversation_id: str):
        if self.storage.delete_conversation(conversation_id):
            conversations = self.storage.list_conversations()
            self.sidebar.update_conversations(conversations)
            
            if self.current_conversation and self.current_conversation.id == conversation_id:
                self.current_conversation = None
                self.chat_view.clear()
                self.stats_panel.update_stats(None)

    def _duplicate_conversation(self, conversation_id: str) -> None:
        src = self.storage.load_conversation(conversation_id)
        if not src:
            QMessageBox.warning(self, "复制失败", "未找到要复制的会话")
            return

        # Deep copy via dict roundtrip (keeps messages/settings intact)
        dup = Conversation.from_dict(src.to_dict())
        dup.id = str(uuid.uuid4())
        now = datetime.now()
        dup.created_at = now
        dup.updated_at = now

        base_title = (src.title or "New Chat").strip() or "New Chat"
        dup.title = f"{base_title}（副本）"

        if not self.storage.save_conversation(dup):
            QMessageBox.warning(self, "复制失败", "保存会话副本失败")
            return

        conversations = self.storage.list_conversations()
        self.sidebar.update_conversations(conversations)
        self.sidebar.select_conversation(dup.id)
        self._on_conversation_selected(dup.id)
    
    def _on_prompt_optimize_started(self, conversation_id: str, request_id: str) -> None:
        if self.current_conversation and self.current_conversation.id == conversation_id:
            try:
                self.input_area.set_prompt_optimize_busy(True)
            except Exception:
                pass

    def _on_prompt_optimize_complete(self, conversation_id: str, request_id: str, text: str) -> None:
        if not self.current_conversation or self.current_conversation.id != conversation_id:
            return
        try:
            self.input_area.set_prompt_optimize_busy(False)
            self.input_area.text_input.setPlainText((text or '').strip())
            cursor = self.input_area.text_input.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.input_area.text_input.setTextCursor(cursor)
            self.input_area.text_input.setFocus()
        except Exception:
            pass

    def _on_prompt_optimize_error(self, conversation_id: str, request_id: str, err: str) -> None:
        if not self.current_conversation or self.current_conversation.id != conversation_id:
            return
        try:
            self.input_area.set_prompt_optimize_busy(False)
        except Exception:
            pass
        QMessageBox.warning(self, '提示词优化失败', err or '未知错误')

    def _on_prompt_optimize_requested(self, raw_text: str) -> None:
        if not self.current_conversation:
            self.current_conversation = Conversation()

        if self.message_runtime.is_streaming(self.current_conversation.id):
            QMessageBox.information(self, '提示', '当前会话正在生成中，请先停止或等待完成。')
            return

        text = (raw_text or '').strip()
        if not text:
            return

        provider_id = self.input_area.get_selected_provider_id()
        base_model = self.input_area.get_selected_model()

        provider = None
        for p in self.providers:
            if p.id == provider_id:
                provider = p
                break

        if not provider:
            QMessageBox.warning(self, '错误', '请先在设置中配置服务商')
            return

        if not base_model:
            QMessageBox.warning(self, '错误', '请选择一个模型')
            return

        # Allow per-conversation override
        settings = dict(self.current_conversation.settings or {})
        opt_model = (settings.get('prompt_optimizer_model') or '').strip() or base_model
        opt_sys = (settings.get('prompt_optimizer_system_prompt') or '').strip() or None

        if not opt_sys:
            try:
                po = self._app_settings.get("prompt_optimizer") or {}
                templates = po.get("templates") if isinstance(po.get("templates"), dict) else {}
                sel = (po.get("selected_template") or "default")
                opt_sys = (templates.get(sel) or "").strip() or None
            except Exception:
                opt_sys = None

        self.prompt_optimizer.start(
            provider=provider,
            conversation_id=self.current_conversation.id,
            raw_prompt=text,
            model=opt_model,
            system_prompt=opt_sys,
        )

    def _send_message(self, content: str, images: list):
        if not self.current_conversation:
            self.current_conversation = Conversation()

        # Per-conversation concurrency: block only if THIS conversation is generating.
        if self.message_runtime.is_streaming(self.current_conversation.id):
            QMessageBox.information(self, "提示", "当前会话正在生成中，请稍候或先取消生成。")
            return
        
        provider_id = self.input_area.get_selected_provider_id()
        model = self.input_area.get_selected_model()
        
        provider = None
        for p in self.providers:
            if p.id == provider_id:
                provider = p
                break
        
        if not provider:
            QMessageBox.warning(self, "错误", "请先在设置中配置服务商")
            return
        
        if not model:
            QMessageBox.warning(self, "错误", "请选择一个模型")
            return
        
        self.current_conversation.provider_id = provider_id
        self.current_conversation.model = model

        # Ensure conversation settings exists and has defaults.
        if self.current_conversation.settings is None:
            self.current_conversation.settings = {}
        self.current_conversation.settings.setdefault('show_thinking', bool(self._app_settings.get('show_thinking', True)))

        # Keep UI (stats panel) in sync with the latest selection.
        self.stats_panel.update_stats(self.current_conversation)

        # Persist selection immediately so model switches take effect even before response.
        self.storage.save_conversation(self.current_conversation)

        # 空输入：如果当前会话最后一条是 user 消息，直接基于该会话发送一次
        if not content and not images:
            if self.current_conversation.messages and self.current_conversation.messages[-1].role == 'user':
                self._start_streaming(provider)
            return
        
        user_message = Message(role="user", content=content, images=images)
        user_message.metadata.update({
            'provider_id': provider_id,
            'provider_name': getattr(provider, 'name', ''),
            'model': model,
        })
        self.current_conversation.add_message(user_message)
        
        if len(self.current_conversation.messages) == 1:
            self.current_conversation.generate_title_from_first_message()
        
        self.chat_view.add_message(user_message)
        self.storage.save_conversation(self.current_conversation)
        
        conversations = self.storage.list_conversations()
        self.sidebar.update_conversations(conversations)
        self.sidebar.select_conversation(self.current_conversation.id)
        
        self._start_streaming(provider)
    
    def _start_streaming(self, provider: Provider):
        conversation = self.current_conversation
        conversation_id = getattr(conversation, 'id', '') or ''
        if not conversation_id:
            return

        debug_log_path = None
        if bool(self._app_settings.get('log_stream', False)):
            try:
                debug_log_path = str(self.storage.data_dir / 'stream_debug.log')
            except Exception:
                debug_log_path = None

        enable_thinking = bool((conversation.settings or {}).get('show_thinking', self._app_settings.get('show_thinking', True)))

        # Build a RunPolicy from the UI (InputArea owns mode->policy mapping).
        try:
            policy = self.input_area.build_run_policy(enable_thinking=enable_thinking)
        except Exception:
            # Fallback: use the same core policy builder (no UI dependencies).
            try:
                from core.agent.policy_builder import build_run_policy
                from core.agent.modes.manager import ModeManager

                mm = ModeManager(getattr(conversation, "work_dir", None) or None)
                policy = build_run_policy(
                    mode_slug=str(getattr(conversation, "mode", "chat") or "chat"),
                    enable_thinking=bool(enable_thinking),
                    enable_search=False,
                    enable_mcp=False,
                    mode_manager=mm,
                )
            except Exception:
                from core.agent.policy import RunPolicy

                policy = RunPolicy(mode="chat", enable_thinking=bool(enable_thinking))

        try:
            if conversation is not None:
                conversation.mode = str(getattr(policy, 'mode', '') or '') or (conversation.mode or 'chat')
        except Exception:
            pass

        state = self.message_runtime.start(
            provider,
            conversation,
            policy=policy,
            debug_log_path=debug_log_path,
        )
        if not state:
            return

        # Only disable input / show streaming bubble when user is viewing this conversation.
        if self.current_conversation and self.current_conversation.id == conversation_id:
            self.chat_view.start_streaming_response(model=state.model)
            self.chat_view.restore_streaming_state("", "")
        self._sync_input_enabled()
    
    def _on_token_received(self, conversation_id: str, request_id: str, token: str):
        """Handle token received during streaming - called from main thread."""
        if self.current_conversation and self.current_conversation.id == conversation_id:
            # Ensure UI is in streaming mode (e.g. for multi-turn tool use)
            if not self.chat_view.is_streaming():
                state = self.message_runtime.get_state(conversation_id)
                model = state.model if state else ""
                self.chat_view.start_streaming_response(model)

            self.chat_view.append_streaming_content(token)

    def _on_thinking_received(self, conversation_id: str, request_id: str, thinking: str):
        """Handle thinking received during streaming - called from main thread."""
        if self.current_conversation and self.current_conversation.id == conversation_id:
            # Ensure UI is in streaming mode
            if not self.chat_view.is_streaming():
                state = self.message_runtime.get_state(conversation_id)
                model = state.model if state else ""
                self.chat_view.start_streaming_response(model)

            if bool((self.current_conversation.settings or {}).get('show_thinking', self._app_settings.get('show_thinking', True))):
                self.chat_view.append_streaming_thinking(thinking)

    def _open_conversation_settings(self):
        if not self.current_conversation:
            self.current_conversation = Conversation()

        dlg = ConversationSettingsDialog(
            self.current_conversation,
            providers=self.providers,
            default_show_thinking=bool(self._app_settings.get('show_thinking', True)),
            parent=self
        )
        if dlg.exec():
            dlg.apply_to_conversation()
            self.storage.save_conversation(self.current_conversation)
            self.stats_panel.update_stats(self.current_conversation)

            # Sync input area with updated provider/model
            if self.current_conversation.provider_id:
                for i, p in enumerate(self.providers):
                    if p.id == self.current_conversation.provider_id:
                        self.input_area.provider_combo.setCurrentIndex(i)
                        break
            if self.current_conversation.model:
                self.input_area.model_combo.setCurrentText(self.current_conversation.model)
            # Sync mode selection (settings)
            try:
                mode_slug = str(getattr(self.current_conversation, 'mode', '') or '')
                idx = self.input_area.mode_combo.findData(mode_slug)
                if idx >= 0:
                    self.input_area.mode_combo.blockSignals(True)
                    try:
                        self.input_area.mode_combo.setCurrentIndex(idx)
                    finally:
                        self.input_area.mode_combo.blockSignals(False)
                    try:
                        self.input_area.apply_mode_policy(apply_defaults=False)
                    except Exception:
                        pass
            except Exception:
                pass
            self.input_area.set_show_thinking(bool((self.current_conversation.settings or {}).get('show_thinking', True)))

            conversations = self.storage.list_conversations()
            self.sidebar.update_conversations(conversations)
            self.sidebar.select_conversation(self.current_conversation.id)

    def _on_conversation_show_thinking_changed(self, enabled: bool):
        if not self.current_conversation:
            self.current_conversation = Conversation()
        if self.current_conversation.settings is None:
            self.current_conversation.settings = {}
        self.current_conversation.settings['show_thinking'] = bool(enabled)
        self.storage.save_conversation(self.current_conversation)
    
    def _on_response_step(self, conversation_id: str, request_id: str, message: Message):
        """Handle intermediate message steps (tool calls/results)."""
        target_conv = self.current_conversation if (self.current_conversation and self.current_conversation.id == conversation_id) else self.storage.load_conversation(conversation_id)
        
        if target_conv:
            # Use add_message to handle tool result merging automatically
            target_conv.add_message(message)
            self.storage.save_conversation(target_conv)
            
            if self.current_conversation and self.current_conversation.id == conversation_id:
                if message.role == "assistant":
                    # For assistant step messages (with tool_calls), finish streaming and add to view
                    self.chat_view.finish_streaming_response(message, add_to_view=True)
                    # Re-start streaming for next turn (expecting tool results then more generation)
                    state = self.message_runtime.get_state(conversation_id)
                    if state:
                        self.chat_view.start_streaming_response(model=state.model)
                else:
                    # Tool result message: just add to view
                    self.chat_view.add_message(message)

                # Tool steps may update SessionState (e.g., manage_state -> tasks).
                # Refresh right panel immediately to keep it in sync.
                try:
                    self.stats_panel.update_stats(self.current_conversation)
                except Exception:
                    pass

    def _on_response_complete(self, conversation_id: str, request_id: str, response):
        """Handle response completion - called from main thread."""
        self._sync_input_enabled()

        # Handle None response (Agent mode completion signal - no message to add)
        if response is None:
            # Just clean up streaming UI without adding message
            if self.current_conversation and self.current_conversation.id == conversation_id:
                self.chat_view.finish_streaming_response(Message(role="system", content=""), add_to_view=False)
                self.stats_panel.update_stats(self.current_conversation)
                
                provider_name = ""
                if self.current_conversation.provider_id:
                    for p in self.providers:
                        if p.id == self.current_conversation.provider_id:
                            provider_name = p.name
                            break
                self.chat_view.update_header(
                    provider_name=provider_name,
                    model=self.current_conversation.model or "",
                    msg_count=len(self.current_conversation.messages)
                )
            self._sync_input_enabled()
            return

        if not isinstance(response, Message):
            return

        # Always persist the response to the conversation that initiated the request.
        target = None
        if self.current_conversation and self.current_conversation.id == conversation_id:
            target = self.current_conversation
        else:
            target = self.storage.load_conversation(conversation_id)

        if not target:
            return

        # Check if message was already added (e.g., by _on_response_step in Agent mode)
        message_already_exists = any(m.id == response.id for m in target.messages)
        
        if not message_already_exists:
            target.add_message(response)
        self.storage.save_conversation(target)

        # Refresh sidebar metadata list
        try:
            conversations = self.storage.list_conversations()
            self.sidebar.update_conversations(conversations)
        except Exception:
            pass

        # Only update the visible chat view if the user is still viewing that conversation.
        if self.current_conversation and self.current_conversation.id == conversation_id:
            # Only add to view if not already present
            self.chat_view.finish_streaming_response(response, add_to_view=not message_already_exists)
            self.stats_panel.update_stats(self.current_conversation)

            provider_name = ""
            if self.current_conversation.provider_id:
                for p in self.providers:
                    if p.id == self.current_conversation.provider_id:
                        provider_name = p.name
                        break
            self.chat_view.update_header(
                provider_name=provider_name,
                model=self.current_conversation.model or "",
                msg_count=len(self.current_conversation.messages)
            )

        self._sync_input_enabled()
    
    def _on_response_error(self, conversation_id: str, request_id: str, error: str):
        """Handle response error - called from main thread."""
        self._sync_input_enabled()

        content = f"错误: {error}"
        if error == "已取消生成":
            content = "已取消生成"

        error_message = Message(role="assistant", content=content)

        # Persist the error message to the originating conversation so it doesn't get lost.
        target = None
        if self.current_conversation and self.current_conversation.id == conversation_id:
            target = self.current_conversation
        else:
            target = self.storage.load_conversation(conversation_id)

        if target:
            target.add_message(error_message)
            self.storage.save_conversation(target)

        # Only show the error in the UI if user is still on that conversation.
        if self.current_conversation and self.current_conversation.id == conversation_id:
            self.chat_view.finish_streaming_response(error_message)

        self._sync_input_enabled()
    
    def _cancel_generation(self):
        if not self.current_conversation:
            return
        self.message_runtime.cancel(self.current_conversation.id)
    
    def _edit_message(self, message_id: str):
        if not self.current_conversation:
            return
        
        message = None
        for msg in self.current_conversation.messages:
            if msg.id == message_id:
                message = msg
                break
        
        if not message:
            return
        
        dialog = MessageEditorDialog(message, self)
        if dialog.exec():
            message.content = dialog.get_edited_content()
            message.images = dialog.get_edited_images()
            self.chat_view.update_message(message)
            self.storage.save_conversation(self.current_conversation)
    
    def _delete_message(self, message_id: str):
        if not self.current_conversation:
            return
        
        reply = QMessageBox.question(
            self, '删除消息', '确定要删除这条消息吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            deleted_ids = self.current_conversation.delete_message(message_id) or []
            for mid in deleted_ids:
                self.chat_view.remove_message(mid)
            self.stats_panel.update_stats(self.current_conversation)
            self.storage.save_conversation(self.current_conversation)

            provider_name = ""
            if self.current_conversation.provider_id:
                for p in self.providers:
                    if p.id == self.current_conversation.provider_id:
                        provider_name = p.name
                        break
            self.chat_view.update_header(
                provider_name=provider_name,
                model=self.current_conversation.model or "",
                msg_count=len(self.current_conversation.messages)
            )
    
    def _open_provider_settings(self):
        """Quick access to configure the currently selected provider"""
        provider_id = self.input_area.get_selected_provider_id()
        provider = None
        provider_index = 0
        for i, p in enumerate(self.providers):
            if p.id == provider_id:
                provider = p
                provider_index = i
                break
        
        if not provider and self.providers:
            provider = self.providers[0]
            provider_index = 0
        
        from ui.dialogs.provider_dialog import ProviderDialog
        dialog = ProviderDialog(provider, parent=self)
        dialog.setWindowTitle(f"配置服务商 - {provider.name if provider else '新建'}")
        if dialog.exec():
            updated_provider = dialog.get_provider()
            if provider:
                self.providers[provider_index] = updated_provider
            else:
                self.providers.append(updated_provider)
            self.storage.save_providers(self.providers)
            self.input_area.set_providers(self.providers)
            # Re-select the provider
            for i, p in enumerate(self.providers):
                if p.id == updated_provider.id:
                    self.input_area.provider_combo.setCurrentIndex(i)
                    break
    
    def _open_settings(self):
        work_dir = ""
        try:
            work_dir = str(getattr(self.current_conversation, "work_dir", "") or "") if self.current_conversation else ""
        except Exception:
            work_dir = ""

        dialog = SettingsDialog(self.providers, current_settings=self._app_settings, parent=self, work_dir=work_dir)
        if dialog.exec():
            self.providers = dialog.get_providers()
            self.storage.save_providers(self.providers)
            self.input_area.set_providers(self.providers)
            
            self._app_settings['show_stats'] = dialog.get_show_stats()
            self._app_settings['theme'] = dialog.get_theme()
            self._app_settings['show_thinking'] = dialog.get_show_thinking()
            self._app_settings['log_stream'] = dialog.get_log_stream()
            self._app_settings['proxy_url'] = dialog.get_proxy_url()
            self._app_settings.update(dialog.get_auto_approve_settings())

            # New: context defaults + prompt templates
            try:
                self._app_settings.update(dialog.get_context_settings())
            except Exception:
                pass
            try:
                self._app_settings.update(dialog.get_prompt_settings())
            except Exception:
                pass

            self._apply_proxy()
            
            # Apply updated permissions to McpManager immediately
            self.mcp_manager.update_permissions(self._app_settings)

            self.storage.save_settings(self._app_settings)

            # Refresh core-level settings cache (so PromptManager/request builder picks up changes without restart)
            try:
                from core.config.app_settings import set_cached_settings
                set_cached_settings(self._app_settings)
            except Exception:
                pass

            self.stats_panel.setVisible(self._app_settings['show_stats'])
            self.toggle_stats_action.setChecked(self._app_settings['show_stats'])
            self._apply_theme()
    
    def _toggle_stats_panel(self, visible: bool):
        self.stats_panel.setVisible(visible)
        self._app_settings['show_stats'] = bool(visible)
        self.storage.save_settings(self._app_settings)
    
    def _show_about(self):
        QMessageBox.about(
            self, "关于 PyChat",
            "<h2>PyChat</h2>"
            "<p>强大的大语言模型会话管理应用</p>"
            "<p>功能:</p>"
            "<ul>"
            "<li>多服务商支持 (OpenAI, Claude, Ollama 等)</li>"
            "<li>会话管理与 JSON 导入/导出</li>"
            "<li>消息编辑与图片支持</li>"
            "<li>思考模式支持</li>"
            "<li>Token 统计与性能指标</li>"
            "</ul>"
            "<p>基于 PyQt6 构建</p>"
        )
