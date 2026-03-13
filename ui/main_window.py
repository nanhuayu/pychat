"""
Main application window - Chinese UI with fixed streaming
"""

import logging
import os
import asyncio
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QMessageBox, QMenu
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from typing import Optional

from models.conversation import Conversation, Message
from models.provider import Provider
from core.container import AppContainer
from ui.runtime.message_runtime import MessageRuntime
from ui.runtime.prompt_optimizer_runtime import PromptOptimizer

from .widgets.sidebar import Sidebar
from .widgets.chat_view import ChatView
from .widgets.input_area import InputArea
from .widgets.stats_panel import StatsPanel

from core.state.services.task_service import TaskService
from .settings.settings_dialog import SettingsDialog
from .dialogs.conversation_settings_dialog import ConversationSettingsDialog
from .presenters.conversation_presenter import ConversationPresenter
from .presenters.message_presenter import MessagePresenter
from .presenters.settings_presenter import SettingsPresenter

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()

        # Centralized dependency container
        self._container = AppContainer()
        self.storage = self._container.storage
        self.client = self._container.client
        self.provider_service = self._container.provider_service
        self.mcp_manager = self._container.mcp_manager
        self.command_registry = self._container.command_registry
        self.message_runtime = MessageRuntime(self.client, mcp_manager=self.mcp_manager, parent=self)

        # Service layer
        self.conv_service = self._container.conv_service
        self.context_service = self._container.context_service
        
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
        self.message_runtime.retry_attempt.connect(self._on_retry_attempt)

        self.prompt_optimizer = PromptOptimizer(self.client, parent=self)
        self.prompt_optimizer.optimize_started.connect(self._on_prompt_optimize_started)
        self.prompt_optimizer.optimize_complete.connect(self._on_prompt_optimize_complete)
        self.prompt_optimizer.optimize_error.connect(self._on_prompt_optimize_error)

        # Presenters — extract business logic out of this God Object
        self._conv_presenter = ConversationPresenter(self)
        self._msg_presenter = MessagePresenter(self)
        self._settings_presenter = SettingsPresenter(self)
        
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
        
        self.input_area = InputArea(
            command_registry=self.command_registry,
            tool_schema_provider=self._get_input_available_tools,
        )
        self.input_area.message_sent.connect(self._send_message)
        self.input_area.cancel_requested.connect(self._cancel_generation)
        self.input_area.conversation_settings_requested.connect(self._open_conversation_settings)
        self.input_area.provider_settings_requested.connect(self._open_provider_settings)
        self.input_area.show_thinking_changed.connect(self._on_conversation_show_thinking_changed)
        self.input_area.mcp_toggled.connect(self._on_conversation_mcp_changed)
        self.input_area.search_toggled.connect(self._on_conversation_search_changed)
        self.input_area.prompt_optimize_requested.connect(self._on_prompt_optimize_requested)
        self.input_area.provider_model_changed.connect(self._on_input_provider_model_changed)
        self.input_area.mode_changed.connect(self._on_conversation_mode_changed)
        self.input_area.slash_command_result.connect(self._on_slash_command_result)

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

    def _get_input_available_tools(self) -> list[dict]:
        try:
            mode_slug = self.input_area.get_selected_mode_slug()
            mode = self.input_area._mode_manager.get(mode_slug)
            return self.mcp_manager.registry.get_all_tool_schemas(
                allowed_groups=mode.group_names(),
            )
        except Exception as e:
            logger.debug("Failed to get tool schemas for input: %s", e)
            return []

    def _on_images_dropped(self, image_sources: list) -> None:
        # Forward images dropped onto the chat area into the input area's attachments.
        try:
            self.input_area.add_attachments(image_sources)
        except Exception as e:
            logger.warning("Failed to add dropped images: %s", e)
    
    def _create_menu_bar(self):
        menubar = self.menuBar()
        menubar.clear()
        
        file_menu = menubar.addMenu("文件")
        conversation_menu = menubar.addMenu("会话")
        
        new_action = QAction("新建会话", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._new_conversation)
        file_menu.addAction(new_action)
        
        import_action = QAction("导入 JSON...", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(lambda: self.sidebar._import_conversation())
        file_menu.addAction(import_action)

        export_menu = QMenu("导出当前会话", self)
        self.export_markdown_action = QAction("导出为 Markdown...", self)
        self.export_markdown_action.triggered.connect(lambda: self._export_conversation("markdown"))
        export_menu.addAction(self.export_markdown_action)

        self.export_json_action = QAction("导出为 JSON...", self)
        self.export_json_action.triggered.connect(lambda: self._export_conversation("json"))
        export_menu.addAction(self.export_json_action)
        file_menu.addMenu(export_menu)
        
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
        
        self.duplicate_conversation_action = QAction("复制当前会话", self)
        self.duplicate_conversation_action.triggered.connect(self._duplicate_current_conversation)
        conversation_menu.addAction(self.duplicate_conversation_action)

        self.delete_conversation_action = QAction("删除当前会话", self)
        self.delete_conversation_action.triggered.connect(self._delete_current_conversation)
        conversation_menu.addAction(self.delete_conversation_action)

        conversation_menu.addSeparator()

        self.conversation_settings_action = QAction("会话设置...", self)
        self.conversation_settings_action.triggered.connect(self._open_conversation_settings)
        conversation_menu.addAction(self.conversation_settings_action)

        self.provider_settings_action = QAction("服务商设置...", self)
        self.provider_settings_action.triggered.connect(self._open_provider_settings)
        conversation_menu.addAction(self.provider_settings_action)

        self.compact_action = QAction("压缩上下文", self)
        self.compact_action.triggered.connect(self._trigger_compact)
        conversation_menu.addAction(self.compact_action)

        edit_menu = menubar.addMenu("编辑")
        
        self.cancel_action = QAction("取消生成", self)
        self.cancel_action.setShortcut("Escape")
        self.cancel_action.triggered.connect(self._cancel_generation)
        edit_menu.addAction(self.cancel_action)
        
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

        self._refresh_menu_action_states()
    
    def _load_data(self):
        self._app_settings = self.storage.load_settings() or {}
        self.mcp_manager.update_permissions(self._app_settings)
        self._apply_proxy()
        try:
            self.client.set_timeout(float(self._app_settings.get("llm_timeout_seconds", 600.0) or 600.0))
        except Exception as e:
            logger.debug("Failed to sync LLM timeout from settings: %s", e)

        self.providers = self.storage.load_providers()
        if not self.providers:
            self.providers = self.provider_service.create_default_providers()
            self.storage.save_providers(self.providers)
        
        self.input_area.set_providers(self.providers)
        try:
            self.input_area.apply_mode_policy(apply_defaults=True)
        except Exception as e:
            logger.debug("Failed to apply initial mode defaults: %s", e)
        self._sync_chat_header_from_input()
        
        conversations = self.conv_service.list_all()
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
            except Exception as e:
                logger.debug("Failed to restore splitter sizes: %s", e)

        # Restore chat splitter sizes (messages/input)
        chat_sizes = self._app_settings.get('chat_splitter_sizes')
        if isinstance(chat_sizes, list) and len(chat_sizes) == 2 and all(isinstance(x, int) for x in chat_sizes):
            try:
                self.chat_splitter.setSizes(chat_sizes)
            except Exception as e:
                logger.debug("Failed to restore chat splitter sizes: %s", e)

    def _on_splitter_moved(self, pos: int, index: int):
        # Persist user layout immediately
        try:
            self._app_settings['splitter_sizes'] = [int(x) for x in self.splitter.sizes()]
            self.storage.save_settings(self._app_settings)
        except Exception as e:
            logger.debug("Failed to persist splitter layout: %s", e)

    def _on_chat_splitter_moved(self, pos: int, index: int):
        try:
            self._app_settings['chat_splitter_sizes'] = [int(x) for x in self.chat_splitter.sizes()]
            self.storage.save_settings(self._app_settings)
        except Exception as e:
            logger.debug("Failed to persist chat splitter layout: %s", e)

    def _sync_input_enabled(self) -> None:
        """Enable/disable input for the currently selected conversation only."""
        try:
            if not self.current_conversation:
                self.input_area.set_streaming_state(False)
                self._refresh_menu_action_states()
                return
            is_streaming = self.message_runtime.is_streaming(self.current_conversation.id)
            self.input_area.set_streaming_state(is_streaming)
            self._refresh_menu_action_states()
        except Exception as e:
            logger.debug("Failed to sync input enabled state: %s", e)
    
    def _apply_theme(self):
        self._settings_presenter.apply_theme()

    def _apply_proxy(self):
        self._settings_presenter.apply_proxy()
    
    def _on_conversation_selected(self, conversation_id: str):
        self._conv_presenter.select(conversation_id)

    def _new_conversation(self):
        self._conv_presenter.new()

    def _apply_task_ops(self, ops: list[dict]) -> None:
        if not self.current_conversation:
            return
        try:
            current_seq = self.current_conversation.next_seq_id()
            state = self.current_conversation.get_state()
            TaskService.handle_ops(state, ops, current_seq)
            state.last_updated_seq = current_seq
            self.current_conversation.set_state(state)
            self.conv_service.save(self.current_conversation)
        except Exception as e:
            logger.warning("Failed to apply task operations: %s", e)
            return

        try:
            self.stats_panel.update_stats(self.current_conversation)
        except Exception as e:
            logger.debug("Failed to update stats after task ops: %s", e)

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
        self._sync_chat_header_from_input(provider_id=provider_id, model=model)

        if not self.current_conversation:
            return

        # Keep in-memory conversation selection consistent; persist only if the conversation already has content.
        try:
            if provider_id:
                self.current_conversation.provider_id = provider_id
            if isinstance(model, str):
                self.current_conversation.model = model.strip()
        except Exception as e:
            logger.debug("Failed to update conversation provider/model: %s", e)

        try:
            self.stats_panel.update_stats(self.current_conversation)
        except Exception as e:
            logger.debug("Failed to update stats panel: %s", e)

        try:
            self.conv_service.save(self.current_conversation)
        except Exception as e:
            logger.warning("Failed to save conversation: %s", e)

        self._refresh_menu_action_states()

    def _on_work_dir_changed(self, path: str):
        """Handle workspace directory change"""
        if self.current_conversation:
            self.current_conversation.work_dir = path
            self.input_area.set_work_dir(path)
            self.conv_service.save(self.current_conversation)
            # Maybe show a toast or status bar message?
    
    def _import_conversation(self, file_path: str):
        self._conv_presenter.import_from_file(file_path)
    
    def _delete_conversation(self, conversation_id: str):
        self._conv_presenter.delete(conversation_id)

    def _duplicate_conversation(self, conversation_id: str) -> None:
        self._conv_presenter.duplicate(conversation_id)
    
    def _on_prompt_optimize_started(self, conversation_id: str, request_id: str) -> None:
        if self.current_conversation and self.current_conversation.id == conversation_id:
            try:
                self.input_area.set_prompt_optimize_busy(True)
            except Exception as e:
                logger.debug("Failed to set prompt optimize busy state: %s", e)

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
        except Exception as e:
            logger.debug("Failed to apply optimized prompt: %s", e)

    def _on_prompt_optimize_error(self, conversation_id: str, request_id: str, err: str) -> None:
        if not self.current_conversation or self.current_conversation.id != conversation_id:
            return
        try:
            self.input_area.set_prompt_optimize_busy(False)
        except Exception as e:
            logger.debug("Failed to reset prompt optimize busy: %s", e)
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

        provider = self.conv_service.find_provider(self.providers, provider_id)
        if not provider:
            QMessageBox.warning(self, '错误', '请先在设置中配置服务商')
            return

        if not base_model:
            QMessageBox.warning(self, '错误', '请选择一个模型')
            return

        # Allow per-conversation override
        settings = dict(self.current_conversation.settings or {})
        opt_model = (
            (settings.get('prompt_optimizer_model') or '').strip()
            or (self._app_settings.get('prompt_optimizer_model') or '').strip()
            or base_model
        )
        opt_sys = (settings.get('prompt_optimizer_system_prompt') or '').strip() or None

        if not opt_sys:
            try:
                po = self._app_settings.get("prompt_optimizer") or {}
                templates = po.get("templates") if isinstance(po.get("templates"), dict) else {}
                sel = (po.get("selected_template") or "default")
                opt_sys = (templates.get(sel) or "").strip() or None
            except Exception as e:
                logger.debug("Failed to get prompt optimizer template: %s", e)
                opt_sys = None

        self.prompt_optimizer.start(
            provider=provider,
            conversation_id=self.current_conversation.id,
            raw_prompt=text,
            model=opt_model,
            system_prompt=opt_sys,
        )

    def _send_message(self, content: str, images: list):
        self._msg_presenter.send(content, images)
    
    def _start_streaming(self, provider: Provider):
        self._msg_presenter.start_streaming(provider)
    
    def _on_token_received(self, conversation_id: str, request_id: str, token: str):
        self._msg_presenter.on_token(conversation_id, request_id, token)

    def _on_thinking_received(self, conversation_id: str, request_id: str, thinking: str):
        self._msg_presenter.on_thinking(conversation_id, request_id, thinking)

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
            self.conv_service.save(self.current_conversation)
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
                    except Exception as e:
                        logger.debug("Failed to apply mode policy in conv settings: %s", e)
            except Exception as e:
                logger.debug("Failed to sync mode selection in conv settings: %s", e)
            self.input_area.set_show_thinking(bool((self.current_conversation.settings or {}).get('show_thinking', True)))
            try:
                settings = self.current_conversation.settings or {}
                default_search, default_mcp = self.input_area.get_mode_default_tool_flags()
                self.input_area.set_tool_toggles(
                    enable_mcp=bool(settings.get('enable_mcp', default_mcp)),
                    enable_search=bool(settings.get('enable_search', default_search)),
                )
            except Exception as e:
                logger.debug("Failed to sync MCP/Search from conversation settings dialog: %s", e)

            conversations = self.conv_service.list_all()
            self.sidebar.update_conversations(conversations)
            self.sidebar.select_conversation(self.current_conversation.id)

    def _on_conversation_show_thinking_changed(self, enabled: bool):
        if not self.current_conversation:
            self.current_conversation = Conversation()
        if self.current_conversation.settings is None:
            self.current_conversation.settings = {}
        self.current_conversation.settings['show_thinking'] = bool(enabled)
        self.conv_service.save(self.current_conversation)

    def _on_conversation_mcp_changed(self, enabled: bool) -> None:
        if not self.current_conversation:
            self.current_conversation = Conversation()
        if self.current_conversation.settings is None:
            self.current_conversation.settings = {}
        self.current_conversation.settings['enable_mcp'] = bool(enabled)
        self.conv_service.save(self.current_conversation)

    def _on_conversation_search_changed(self, enabled: bool) -> None:
        if not self.current_conversation:
            self.current_conversation = Conversation()
        if self.current_conversation.settings is None:
            self.current_conversation.settings = {}
        self.current_conversation.settings['enable_search'] = bool(enabled)
        self.conv_service.save(self.current_conversation)

    def _on_conversation_mode_changed(self, mode_slug: str) -> None:
        if not self.current_conversation:
            self.current_conversation = Conversation()
        self.current_conversation.mode = str(mode_slug or 'chat') or 'chat'
        if self.current_conversation.settings is None:
            self.current_conversation.settings = {}
        self.current_conversation.settings['show_thinking'] = bool(self.input_area.thinking_toggle.isChecked())
        self.current_conversation.settings['enable_mcp'] = bool(self.input_area.is_mcp_enabled())
        self.current_conversation.settings['enable_search'] = bool(self.input_area.is_search_enabled())
        self.conv_service.save(self.current_conversation)
    
    def _on_response_step(self, conversation_id: str, request_id: str, message: Message):
        self._msg_presenter.on_response_step(conversation_id, request_id, message)

    def _on_response_complete(self, conversation_id: str, request_id: str, response):
        self._msg_presenter.on_response_complete(conversation_id, request_id, response)
    
    def _on_response_error(self, conversation_id: str, request_id: str, error: str):
        self._msg_presenter.on_response_error(conversation_id, request_id, error)
    
    def _on_retry_attempt(self, conversation_id: str, request_id: str, detail: str):
        self._msg_presenter.on_retry_attempt(conversation_id, request_id, detail)

    def _trigger_compact(self):
        """Condense current conversation context via ContextService."""
        if not self.current_conversation:
            return
        conv = self.current_conversation
        provider = self.conv_service.find_provider(self.providers, conv.provider_id)
        if not provider:
            self.statusBar().showMessage("未找到对应的 Provider，无法压缩上下文", 3000)
            return
        try:
            self.context_service.compact(conv, provider)
            self.conv_service.save(conv)
            self._load_conversation_messages()
            self.statusBar().showMessage("上下文已压缩", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"压缩失败: {e}", 5000)

    def _cancel_generation(self):
        if not self.current_conversation:
            return
        self.message_runtime.cancel(self.current_conversation.id)

    def _duplicate_current_conversation(self) -> None:
        if not self.current_conversation:
            return
        self._duplicate_conversation(self.current_conversation.id)

    def _delete_current_conversation(self) -> None:
        if not self.current_conversation:
            return
        self._delete_conversation(self.current_conversation.id)

    def _sync_chat_header_from_input(self, provider_id: str | None = None, model: str | None = None) -> None:
        selected_provider_id = provider_id if provider_id is not None else self.input_area.get_selected_provider_id()
        selected_model = model if model is not None else self.input_area.get_selected_model()
        provider_name = ''
        try:
            for provider in getattr(self, 'providers', []) or []:
                if getattr(provider, 'id', '') == selected_provider_id:
                    provider_name = getattr(provider, 'name', '') or ''
                    break
        except Exception as e:
            logger.debug("Failed to resolve provider name for header sync: %s", e)

        msg_count = 0
        try:
            if self.current_conversation:
                msg_count = len(getattr(self.current_conversation, 'messages', []) or [])
        except Exception as e:
            logger.debug("Failed to get message count for header sync: %s", e)

        try:
            self.chat_view.update_header(provider_name=provider_name, model=(selected_model or ''), msg_count=msg_count)
        except Exception as e:
            logger.debug("Failed to sync chat header from input: %s", e)

        self._refresh_menu_action_states()

    def _refresh_menu_action_states(self) -> None:
        has_conversation = bool(self.current_conversation)
        has_messages = bool(has_conversation and getattr(self.current_conversation, 'messages', None))
        is_streaming = bool(has_conversation and self.message_runtime.is_streaming(self.current_conversation.id))

        for action_name, enabled in (
            ('export_markdown_action', has_conversation),
            ('export_json_action', has_conversation),
            ('duplicate_conversation_action', has_conversation),
            ('delete_conversation_action', has_conversation),
            ('conversation_settings_action', has_conversation),
            ('provider_settings_action', True),
            ('compact_action', has_messages),
            ('cancel_action', is_streaming),
        ):
            action = getattr(self, action_name, None)
            if action is not None:
                action.setEnabled(bool(enabled))

    def _export_conversation(self, fmt: str = "markdown"):
        self._conv_presenter.export_current(fmt)

    def _on_slash_command_result(self, result):
        self._conv_presenter.handle_command_result(result)
    
    def _edit_message(self, message_id: str):
        self._msg_presenter.edit(message_id)
    
    def _delete_message(self, message_id: str):
        self._msg_presenter.delete(message_id)
    
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
        except Exception as e:
            logger.debug("Failed to get work_dir for settings: %s", e)
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
            self._app_settings['llm_timeout_seconds'] = dialog.get_llm_timeout_seconds()
            self._app_settings.update(dialog.get_auto_approve_settings())

            # Retry config
            try:
                retry_patch = dialog.get_retry_settings()
                if retry_patch:
                    self._app_settings["retry"] = retry_patch
            except Exception as e:
                logger.debug("Failed to get retry settings: %s", e)

            # New: context defaults + prompt templates
            try:
                self._app_settings.update(dialog.get_context_settings())
            except Exception as e:
                logger.debug("Failed to get context settings: %s", e)
            try:
                self._app_settings.update(dialog.get_prompt_settings())
            except Exception as e:
                logger.debug("Failed to get prompt settings: %s", e)

            self._apply_proxy()
            try:
                self.client.set_timeout(float(self._app_settings.get('llm_timeout_seconds', 600.0) or 600.0))
            except Exception as e:
                logger.debug("Failed to apply updated LLM timeout: %s", e)
            
            # Apply updated permissions to McpManager immediately
            self.mcp_manager.update_permissions(self._app_settings)

            self.storage.save_settings(self._app_settings)

            # Refresh core-level settings cache (so PromptManager/request builder picks up changes without restart)
            try:
                from core.config.app_settings import set_cached_settings
                set_cached_settings(self._app_settings)
            except Exception as e:
                logger.debug("Failed to refresh settings cache: %s", e)

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

    def closeEvent(self, event) -> None:
        try:
            asyncio.run(self.mcp_manager.shutdown())
        except Exception as e:
            logger.debug("Failed to shutdown MCP sessions on exit: %s", e)
        super().closeEvent(event)
