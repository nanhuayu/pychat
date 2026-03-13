"""Conversation lifecycle presenter.

Extracts conversation CRUD + selection logic from MainWindow,
reducing it by ~170 lines.
"""
from __future__ import annotations

import logging
import json
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from models.conversation import Conversation, Message

if TYPE_CHECKING:
    from ui.main_window import MainWindow

logger = logging.getLogger(__name__)


class ConversationPresenter:
    """Handles conversation selection, creation, import, delete, duplicate."""

    def __init__(self, host: MainWindow) -> None:
        self._host = host

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(self, conversation_id: str) -> None:
        host = self._host
        conversation = host.conv_service.load(conversation_id)
        if not conversation:
            return

        host._syncing_input_selection = True
        try:
            host.current_conversation = conversation
            host.chat_view.load_conversation(conversation)
            host.stats_panel.update_stats(conversation)

            # Sync per-conversation toggles
            show_thinking_default = bool(host._app_settings.get("show_thinking", True))
            show_thinking = bool(
                (conversation.settings or {}).get("show_thinking", show_thinking_default)
            )
            host.input_area.set_show_thinking(show_thinking)

            # Sync provider (so model list is populated), then model
            provider_name = ""
            if conversation.provider_id:
                for i, provider in enumerate(host.providers):
                    if provider.id == conversation.provider_id:
                        host.input_area.provider_combo.setCurrentIndex(i)
                        provider_name = provider.name
                        break

            if conversation.model:
                host.input_area.model_combo.setCurrentText(conversation.model)

            # Sync mode selection
            try:
                mode_slug = str(getattr(conversation, "mode", "") or "")
                idx = host.input_area.mode_combo.findData(mode_slug)
                if idx >= 0:
                    host.input_area.mode_combo.blockSignals(True)
                    try:
                        host.input_area.mode_combo.setCurrentIndex(idx)
                    finally:
                        host.input_area.mode_combo.blockSignals(False)
                    try:
                        host.input_area.apply_mode_policy(apply_defaults=False)
                    except Exception as e:
                        logger.debug("Failed to apply mode policy during select: %s", e)
            except Exception as e:
                logger.debug("Failed to sync mode selection during select: %s", e)

            try:
                conv_settings = conversation.settings or {}
                default_search, default_mcp = host.input_area.get_mode_default_tool_flags()
                host.input_area.set_tool_toggles(
                    enable_mcp=bool(conv_settings.get("enable_mcp", default_mcp)),
                    enable_search=bool(conv_settings.get("enable_search", default_search)),
                )
            except Exception as e:
                logger.debug("Failed to sync MCP/Search toggles during select: %s", e)

            # Update chat header
            host.chat_view.update_header(
                provider_name=provider_name,
                model=conversation.model or "",
                msg_count=len(conversation.messages),
            )
            work_dir = getattr(conversation, "work_dir", "")
            host.chat_view.update_work_dir(work_dir)
            host.input_area.set_work_dir(work_dir)
            host.input_area.set_conversation(conversation)

            # Restore streaming UI if this conversation is currently generating
            stream_state = host.message_runtime.get_state(conversation.id)
            if stream_state:
                host.chat_view.start_streaming_response(model=stream_state.model)
                host.chat_view.restore_streaming_state(
                    visible_text=stream_state.visible_text,
                    thinking_text=stream_state.thinking_text,
                )

            host._sync_input_enabled()
        finally:
            host._syncing_input_selection = False

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def new(self) -> None:
        host = self._host
        host.current_conversation = Conversation()
        try:
            host.current_conversation.provider_id = host.input_area.get_selected_provider_id()
            host.current_conversation.model = host.input_area.get_selected_model()
            host.current_conversation.mode = host.input_area.get_selected_mode_slug()
            host.current_conversation.settings = dict(host.current_conversation.settings or {})
            host.current_conversation.settings["show_thinking"] = bool(host.input_area.thinking_toggle.isChecked())
            host.current_conversation.settings["enable_mcp"] = bool(host.input_area.is_mcp_enabled())
            host.current_conversation.settings["enable_search"] = bool(host.input_area.is_search_enabled())
        except Exception as e:
            logger.debug("Failed to seed new conversation selection: %s", e)
        host.chat_view.clear()
        host.stats_panel.update_stats(None)
        host._sync_chat_header_from_input()
        host.chat_view.update_work_dir("")
        host.input_area.set_work_dir("")
        host.input_area.set_conversation(host.current_conversation)
        try:
            host.conv_service.save(host.current_conversation)
        except Exception as e:
            logger.debug("Failed to save new conversation shell: %s", e)
        host._sync_input_enabled()

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_from_file(self, file_path: str) -> None:
        host = self._host
        conversation = host.conv_service.import_from_file(file_path)
        if conversation:
            conversations = host.conv_service.list_all()
            host.sidebar.update_conversations(conversations)
            host.sidebar.select_conversation(conversation.id)
            self.select(conversation.id)
            QMessageBox.information(host, "导入成功", f"已导入会话: {conversation.title}")
        else:
            QMessageBox.warning(host, "导入失败", "无法导入会话，请检查 JSON 格式")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, conversation_id: str) -> None:
        host = self._host
        if host.conv_service.delete(conversation_id):
            conversations = host.conv_service.list_all()
            host.sidebar.update_conversations(conversations)

            if host.current_conversation and host.current_conversation.id == conversation_id:
                host.current_conversation = None
                host.chat_view.clear()
                host.stats_panel.update_stats(None)
                host._sync_chat_header_from_input()
                host.chat_view.update_work_dir("")
                host.input_area.set_work_dir("")
                host.input_area.set_conversation(None)
                host._sync_input_enabled()

    # ------------------------------------------------------------------
    # Duplicate
    # ------------------------------------------------------------------

    def duplicate(self, conversation_id: str) -> None:
        host = self._host
        src = host.conv_service.load(conversation_id)
        if not src:
            QMessageBox.warning(host, "复制失败", "未找到要复制的会话")
            return

        dup = host.conv_service.duplicate(src)

        if not host.conv_service.save(dup):
            QMessageBox.warning(host, "复制失败", "保存会话副本失败")
            return

        conversations = host.conv_service.list_all()
        host.sidebar.update_conversations(conversations)
        host.sidebar.select_conversation(dup.id)
        self.select(dup.id)

    # ------------------------------------------------------------------
    # Commands / export
    # ------------------------------------------------------------------

    def export_current(self, fmt: str = "markdown") -> None:
        host = self._host
        if not host.current_conversation:
            return

        conv = host.current_conversation
        default_name = (conv.title or "conversation").replace(" ", "_")

        if fmt == "json":
            path, _ = QFileDialog.getSaveFileName(
                host,
                "Export Conversation",
                f"{default_name}.json",
                "JSON (*.json)",
            )
            if path:
                data = conv.to_dict() if hasattr(conv, "to_dict") else {"messages": [m.to_dict() for m in conv.messages]}
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                host.statusBar().showMessage(f"已导出到 {path}", 3000)
            return

        path, _ = QFileDialog.getSaveFileName(
            host,
            "Export Conversation",
            f"{default_name}.md",
            "Markdown (*.md)",
        )
        if not path:
            return

        lines = [f"# {conv.title or 'Conversation'}\n"]
        for msg in conv.messages:
            if msg.role == "system":
                continue
            role = msg.role.upper()
            content = msg.content or ""
            lines.append(f"## {role}\n\n{content}\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        host.statusBar().showMessage(f"已导出到 {path}", 3000)

    def handle_command_result(self, result) -> None:
        host = self._host
        from core.commands import CommandAction, CommandResult

        if isinstance(result, str):
            self._append_info_message(result)
            return

        if not isinstance(result, CommandResult):
            return

        if result.action == CommandAction.CLEAR:
            self.new()
            return

        if result.action == CommandAction.COMPACT:
            host._trigger_compact()
            return

        if result.action == CommandAction.MODE_SWITCH:
            slug = result.data
            if slug:
                idx = host.input_area.mode_combo.findData(slug)
                if idx >= 0:
                    host.input_area.mode_combo.setCurrentIndex(idx)
            return

        if result.action == CommandAction.SKILL:
            skill_name = str(result.data or "").strip()
            if not skill_name or not host.current_conversation:
                return
            if host.skill_service.activate_for_conversation(host.current_conversation, skill_name):
                host.conv_service.save(host.current_conversation)
                self._append_info_message(f"\u2705 Skill **{skill_name}** activated for this conversation.")
            else:
                self._append_info_message(f"Skill `{skill_name}` not found for the current workspace.")
            return

        if result.action == CommandAction.EXPORT:
            self.export_current((result.data or "markdown").strip())
            return

        if result.action == CommandAction.DISPLAY and result.display_text:
            self._append_info_message(result.display_text)

    def _append_info_message(self, content: str) -> None:
        host = self._host
        if not host.current_conversation:
            return
        info_msg = Message(role="assistant", content=content)
        host.current_conversation.messages.append(info_msg)
        host.chat_view.add_message(info_msg)
        host.conv_service.save(host.current_conversation)
