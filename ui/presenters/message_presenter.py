"""Message & streaming presenter.

Extracts message sending, streaming control, and response handling
from MainWindow, reducing it by ~300 lines.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QMessageBox

from models.conversation import Conversation, Message
from models.provider import Provider

if TYPE_CHECKING:
    from ui.main_window import MainWindow

logger = logging.getLogger(__name__)


class MessagePresenter:
    """Handles message sending, streaming, and response lifecycle."""

    def __init__(self, host: MainWindow) -> None:
        self._host = host

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send(self, content: str, images: list) -> None:
        host = self._host

        if not host.current_conversation:
            host.current_conversation = Conversation()

        if host.message_runtime.is_streaming(host.current_conversation.id):
            QMessageBox.information(host, "提示", "当前会话正在生成中，请稍候或先取消生成。")
            return

        provider_id = host.input_area.get_selected_provider_id()
        model = host.input_area.get_selected_model()

        provider = self._find_provider(provider_id)
        if not provider:
            QMessageBox.warning(host, "错误", "请先在设置中配置服务商")
            return
        if not model:
            QMessageBox.warning(host, "错误", "请选择一个模型")
            return

        host.current_conversation.provider_id = provider_id
        host.current_conversation.model = model

        if host.current_conversation.settings is None:
            host.current_conversation.settings = {}
        host.current_conversation.settings.setdefault(
            "show_thinking", bool(host._app_settings.get("show_thinking", True))
        )
        host.stats_panel.update_stats(host.current_conversation)
        host.conv_service.save(host.current_conversation)

        # Empty input: if last message is user, just re-stream
        if not content and not images:
            if (
                host.current_conversation.messages
                and host.current_conversation.messages[-1].role == "user"
            ):
                self.start_streaming(provider)
            return

        user_message = Message(role="user", content=content, images=images)
        user_message.metadata.update(
            {
                "provider_id": provider_id,
                "provider_name": getattr(provider, "name", ""),
                "model": model,
            }
        )
        host.current_conversation.add_message(user_message)

        if len(host.current_conversation.messages) == 1:
            host.current_conversation.generate_title_from_first_message()

        host.chat_view.add_message(user_message)
        host.conv_service.save(host.current_conversation)

        conversations = host.conv_service.list_all()
        host.sidebar.update_conversations(conversations)
        host.sidebar.select_conversation(host.current_conversation.id)

        self.start_streaming(provider)

    # ------------------------------------------------------------------
    # Start streaming
    # ------------------------------------------------------------------

    def start_streaming(self, provider: Provider) -> None:
        host = self._host
        conversation = host.current_conversation
        conversation_id = getattr(conversation, "id", "") or ""
        if not conversation_id:
            return

        from services.agent_service import AgentService
        debug_log_path = AgentService.get_debug_log_path(host._app_settings, host.storage)

        enable_thinking = bool(
            (conversation.settings or {}).get(
                "show_thinking", host._app_settings.get("show_thinking", True)
            )
        )

        retry_cfg = None
        try:
            from core.config.schema import RetryConfig

            raw_retry = host._app_settings.get("retry")
            if raw_retry and isinstance(raw_retry, dict):
                retry_cfg = RetryConfig.from_dict(raw_retry)
        except Exception as e:
            logger.debug("Failed to load retry config: %s", e)

        try:
            policy = host.input_area.build_run_policy(
                enable_thinking=enable_thinking, retry_config=retry_cfg
            )
        except Exception as e:
            logger.warning("Failed to build run policy from input area: %s", e)
            try:
                policy = AgentService.build_run_policy(
                    conversation=conversation,
                    app_settings=host._app_settings,
                    enable_thinking=enable_thinking,
                )
            except Exception as e:
                logger.warning("Failed to build fallback run policy: %s", e)
                from core.task.types import RunPolicy

                policy = RunPolicy(mode="chat", enable_thinking=bool(enable_thinking))

        try:
            if conversation is not None:
                conversation.mode = (
                    str(getattr(policy, "mode", "") or "")
                    or (conversation.mode or "chat")
                )
        except Exception as e:
            logger.debug("Failed to sync conversation mode from policy: %s", e)

        state = host.message_runtime.start(
            provider,
            conversation,
            policy=policy,
            debug_log_path=debug_log_path,
        )
        if not state:
            return

        if host.current_conversation and host.current_conversation.id == conversation_id:
            host.chat_view.start_streaming_response(model=state.model)
            host.chat_view.restore_streaming_state("", "")
        host._sync_input_enabled()

    # ------------------------------------------------------------------
    # Streaming callbacks
    # ------------------------------------------------------------------

    def on_token(self, conversation_id: str, request_id: str, token: str) -> None:
        host = self._host
        if host.current_conversation and host.current_conversation.id == conversation_id:
            if not host.chat_view.is_streaming():
                state = host.message_runtime.get_state(conversation_id)
                model = state.model if state else ""
                host.chat_view.start_streaming_response(model)
            host.chat_view.append_streaming_content(token)

    def on_thinking(self, conversation_id: str, request_id: str, thinking: str) -> None:
        host = self._host
        if host.current_conversation and host.current_conversation.id == conversation_id:
            if not host.chat_view.is_streaming():
                state = host.message_runtime.get_state(conversation_id)
                model = state.model if state else ""
                host.chat_view.start_streaming_response(model)
            if bool(
                (host.current_conversation.settings or {}).get(
                    "show_thinking", host._app_settings.get("show_thinking", True)
                )
            ):
                host.chat_view.append_streaming_thinking(thinking)

    def on_response_step(
        self, conversation_id: str, request_id: str, message: Message
    ) -> None:
        host = self._host
        target_conv = (
            host.current_conversation
            if (host.current_conversation and host.current_conversation.id == conversation_id)
            else host.conv_service.load(conversation_id)
        )
        if not target_conv:
            return

        msg_seq = getattr(message, "seq_id", None)
        if msg_seq and any(
            getattr(m, "seq_id", None) == msg_seq for m in target_conv.messages
        ):
            return

        target_conv.add_message(message)
        host.conv_service.save(target_conv)

        if host.current_conversation and host.current_conversation.id == conversation_id:
            if message.role == "assistant":
                host.chat_view.finish_streaming_response(message, add_to_view=True)
                state = host.message_runtime.get_state(conversation_id)
                if state:
                    host.chat_view.start_streaming_response(model=state.model)
            else:
                host.chat_view.add_message(message)

            try:
                host.stats_panel.update_stats(host.current_conversation)
            except Exception as e:
                logger.debug("Failed to update stats in response step: %s", e)

    def on_response_complete(
        self, conversation_id: str, request_id: str, response
    ) -> None:
        host = self._host
        host._sync_input_enabled()

        if response is None:
            if host.current_conversation and host.current_conversation.id == conversation_id:
                host.chat_view.finish_streaming_response(
                    Message(role="system", content=""), add_to_view=False
                )
                host.stats_panel.update_stats(host.current_conversation)
                self._update_header(conversation_id)
            host._sync_input_enabled()
            return

        if not isinstance(response, Message):
            return

        target = None
        if host.current_conversation and host.current_conversation.id == conversation_id:
            target = host.current_conversation
        else:
            target = host.conv_service.load(conversation_id)

        if not target:
            return

        message_already_exists = any(m.id == response.id for m in target.messages)
        if not message_already_exists:
            target.add_message(response)
        host.conv_service.save(target)

        try:
            conversations = host.conv_service.list_all()
            host.sidebar.update_conversations(conversations)
        except Exception as e:
            logger.debug("Failed to refresh sidebar after response complete: %s", e)

        if host.current_conversation and host.current_conversation.id == conversation_id:
            host.chat_view.finish_streaming_response(
                response, add_to_view=not message_already_exists
            )
            host.stats_panel.update_stats(host.current_conversation)
            self._update_header(conversation_id)

        host._sync_input_enabled()

    def on_response_error(
        self, conversation_id: str, request_id: str, error: str
    ) -> None:
        host = self._host
        host._sync_input_enabled()

        content = f"错误: {error}"
        if error == "已取消生成":
            content = "已取消生成"

        error_message = Message(role="assistant", content=content)

        target = None
        if host.current_conversation and host.current_conversation.id == conversation_id:
            target = host.current_conversation
        else:
            target = host.conv_service.load(conversation_id)

        if target:
            target.add_message(error_message)
            host.conv_service.save(target)

        if host.current_conversation and host.current_conversation.id == conversation_id:
            host.chat_view.finish_streaming_response(error_message)

        host._sync_input_enabled()

    def on_retry_attempt(
        self, conversation_id: str, request_id: str, detail: str
    ) -> None:
        host = self._host
        if host.current_conversation and host.current_conversation.id == conversation_id:
            host.statusBar().showMessage(f"重试中: {detail}", 5000)

    # ------------------------------------------------------------------
    # Edit / Delete
    # ------------------------------------------------------------------

    def edit(self, message_id: str) -> None:
        host = self._host
        if not host.current_conversation:
            return

        message = None
        for msg in host.current_conversation.messages:
            if msg.id == message_id:
                message = msg
                break
        if not message:
            return

        from ui.dialogs.message_editor import MessageEditorDialog

        dialog = MessageEditorDialog(message, host)
        if dialog.exec():
            message.content = dialog.get_edited_content()
            message.images = dialog.get_edited_images()
            host.chat_view.update_message(message)
            host.conv_service.save(host.current_conversation)

    def delete(self, message_id: str) -> None:
        host = self._host
        if not host.current_conversation:
            return

        reply = QMessageBox.question(
            host,
            "删除消息",
            "确定要删除这条消息吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            deleted_ids = host.current_conversation.delete_message(message_id) or []
            for mid in deleted_ids:
                host.chat_view.remove_message(mid)
            host.stats_panel.update_stats(host.current_conversation)
            host.conv_service.save(host.current_conversation)
            self._update_header(host.current_conversation.id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_provider(self, provider_id: str):
        for p in self._host.providers:
            if p.id == provider_id:
                return p
        return None

    def _update_header(self, conversation_id: str) -> None:
        host = self._host
        if not (
            host.current_conversation
            and host.current_conversation.id == conversation_id
        ):
            return
        provider_name = ""
        if host.current_conversation.provider_id:
            for p in host.providers:
                if p.id == host.current_conversation.provider_id:
                    provider_name = p.name
                    break
        host.chat_view.update_header(
            provider_name=provider_name,
            model=host.current_conversation.model or "",
            msg_count=len(host.current_conversation.messages),
        )
