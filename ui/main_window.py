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
from services.chat_service import ChatService
from services.provider_service import ProviderService
from controllers.stream_manager import StreamManager

from .widgets.sidebar import Sidebar
from .widgets.chat_view import ChatView
from .widgets.input_area import InputArea
from .widgets.stats_panel import StatsPanel
from .settings.settings_dialog import SettingsDialog
from .dialogs.message_editor import MessageEditorDialog
from .dialogs.conversation_settings_dialog import ConversationSettingsDialog


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        self.storage = StorageService()
        self.chat_service = ChatService()
        self.provider_service = ProviderService()
        self.stream_manager = StreamManager(self.chat_service, parent=self)
        
        self.providers: list[Provider] = []
        self.current_conversation: Optional[Conversation] = None
        self._app_settings: dict = {}

        # Streaming events (thread-safe; StreamManager normalizes + guards request_id)
        self.stream_manager.token_received.connect(self._on_token_received)
        self.stream_manager.thinking_received.connect(self._on_thinking_received)
        self.stream_manager.response_step.connect(self._on_response_step)
        self.stream_manager.response_complete.connect(self._on_response_complete)
        self.stream_manager.response_error.connect(self._on_response_error)
        
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
        
        self.input_area = InputArea()
        self.input_area.message_sent.connect(self._send_message)
        self.input_area.conversation_settings_requested.connect(self._open_conversation_settings)
        self.input_area.provider_settings_requested.connect(self._open_provider_settings)
        self.input_area.show_thinking_changed.connect(self._on_conversation_show_thinking_changed)

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
                self.input_area.set_enabled(True)
                return
            self.input_area.set_enabled(not self.stream_manager.is_streaming(self.current_conversation.id))
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
    
    def _on_conversation_selected(self, conversation_id: str):
        conversation = self.storage.load_conversation(conversation_id)
        if conversation:
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
            
            # Update chat header
            self.chat_view.update_header(
                provider_name=provider_name,
                model=conversation.model or "",
                msg_count=len(conversation.messages)
            )

            # Restore streaming UI if this conversation is currently generating.
            stream_state = self.stream_manager.get_state(conversation.id)
            if stream_state:
                self.chat_view.start_streaming_response(model=stream_state.model)
                self.chat_view.restore_streaming_state(
                    visible_text=stream_state.visible_text,
                    thinking_text=stream_state.thinking_text
                )

            self._sync_input_enabled()
    
    def _new_conversation(self):
        self.current_conversation = Conversation()
        self.chat_view.clear()
        self.stats_panel.update_stats(None)
        self.chat_view.update_header(provider_name="", model="", msg_count=0)
        self._sync_input_enabled()
    
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
    
    def _send_message(self, content: str, images: list):
        if not self.current_conversation:
            self.current_conversation = Conversation()

        # Per-conversation concurrency: block only if THIS conversation is generating.
        if self.stream_manager.is_streaming(self.current_conversation.id):
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

        # Get tool toggles from input area
        enable_search = self.input_area.is_search_enabled()
        enable_mcp = self.input_area.is_mcp_enabled()

        state = self.stream_manager.start(
            provider,
            conversation,
            enable_thinking=enable_thinking,
            enable_search=enable_search,
            enable_mcp=enable_mcp,
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
            self.chat_view.append_streaming_content(token)

    def _on_thinking_received(self, conversation_id: str, request_id: str, thinking: str):
        """Handle thinking received during streaming - called from main thread."""
        if self.current_conversation and self.current_conversation.id == conversation_id:
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
            # target_conv.add_message(message) 
            # Note: add_message might auto-update IDs? Use append if simple. 
            # Check conversation.py. add_message is safer.
            # But add_message is part of Conversation class? yes.
            target_conv.messages.append(message)
            self.storage.save_conversation(target_conv)
            
            if self.current_conversation and self.current_conversation.id == conversation_id:
                if message.role == "assistant":
                    self.chat_view.finish_streaming_response(message)
                else:
                    self.chat_view.add_message(message)

    def _on_response_complete(self, conversation_id: str, request_id: str, response):
        """Handle response completion - called from main thread."""
        self._sync_input_enabled()

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
            self.chat_view.finish_streaming_response(response)
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

        error_message = Message(role="assistant", content=f"未知错误: {error}")

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
        self.stream_manager.cancel(self.current_conversation.id)
    
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
            self.current_conversation.delete_message(message_id)
            self.chat_view.remove_message(message_id)
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
        dialog = SettingsDialog(self.providers, current_settings=self._app_settings, parent=self)
        if dialog.exec():
            self.providers = dialog.get_providers()
            self.storage.save_providers(self.providers)
            self.input_area.set_providers(self.providers)
            
            self._app_settings['show_stats'] = dialog.get_show_stats()
            self._app_settings['theme'] = dialog.get_theme()
            self._app_settings['show_thinking'] = dialog.get_show_thinking()
            self._app_settings['log_stream'] = dialog.get_log_stream()
            self.storage.save_settings(self._app_settings)
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
