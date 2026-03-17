"""Conversation lifecycle presenter.

Extracts conversation CRUD + selection logic from MainWindow,
reducing it by ~170 lines.
"""
from __future__ import annotations

import asyncio
import logging
import json
from typing import TYPE_CHECKING, Any

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from core.tools.permissions import ToolPermissionPolicy
from models.conversation import Conversation, Message
from services.command_service import CommandExecutionDenied

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
        conversation = host.services.conv_service.load(conversation_id)
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
        host.current_conversation = host._seed_conversation_from_input(Conversation())
        try:
            host.current_conversation = host._seed_conversation_from_input(host.current_conversation)
        except Exception as e:
            logger.debug("Failed to seed new conversation selection: %s", e)
        host.chat_view.clear()
        host.stats_panel.update_stats(None)
        host._sync_chat_header_from_input()
        work_dir = str(getattr(host.current_conversation, "work_dir", "") or "")
        host.chat_view.update_work_dir(work_dir)
        host.input_area.set_work_dir(work_dir)
        host.input_area.set_conversation(host.current_conversation)
        try:
            host.services.conv_service.save(host.current_conversation)
        except Exception as e:
            logger.debug("Failed to save new conversation shell: %s", e)
        host._sync_input_enabled()

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_from_file(self, file_path: str) -> None:
        host = self._host
        conversation = host.services.conv_service.import_from_file(file_path)
        if conversation:
            conversations = host.services.conv_service.list_all()
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
        try:
            asyncio.run(host.services.tool_manager.close_conversation_sessions(conversation_id))
        except Exception as e:
            logger.debug("Failed to close MCP sessions for deleted conversation: %s", e)
        if host.services.conv_service.delete(conversation_id):
            conversations = host.services.conv_service.list_all()
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
        src = host.services.conv_service.load(conversation_id)
        if not src:
            QMessageBox.warning(host, "复制失败", "未找到要复制的会话")
            return

        dup = host.services.conv_service.duplicate(src)

        if not host.services.conv_service.save(dup):
            QMessageBox.warning(host, "复制失败", "保存会话副本失败")
            return

        conversations = host.services.conv_service.list_all()
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
        from core.commands import CommandAction, CommandResult, PromptInvocation, ShellInvocation

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
            self._switch_mode(str(result.data or ""))
            return

        if result.action == CommandAction.PROMPT_RUN:
            payload = result.data if isinstance(result.data, PromptInvocation) else None
            if payload is None:
                return
            self._run_prompt_invocation(payload)
            return

        if result.action == CommandAction.SHELL_RUN:
            payload = result.data if isinstance(result.data, ShellInvocation) else None
            shell_command = str(payload.command_text if payload else "").strip()
            if not shell_command:
                return

            self._run_shell_command(payload)
            return

        if result.action == CommandAction.EXPORT:
            self.export_current((result.data or "markdown").strip())
            return

        if result.action == CommandAction.DISPLAY and result.display_text:
            self._append_info_message(result.display_text)

    def _run_prompt_invocation(self, payload) -> None:
        host = self._host
        if not host.current_conversation:
            self.new()

        conversation = host.current_conversation
        if conversation is None:
            return

        mode_slug = str(getattr(payload, "mode_slug", "") or "").strip().lower()
        if mode_slug:
            self._switch_mode(mode_slug, persist=False)
            try:
                conversation.mode = mode_slug
            except Exception as exc:
                logger.debug("Failed to sync conversation mode for prompt invocation: %s", exc)

        updates = getattr(payload, "document_updates", {}) or {}
        if isinstance(updates, dict) and updates:
            self._apply_document_updates(conversation, updates)
            try:
                host.services.conv_service.save(conversation)
            except Exception as exc:
                logger.debug("Failed to save prompt invocation state: %s", exc)

        metadata = dict(getattr(payload, "metadata", {}) or {})
        command_run = metadata.get("command_run") if isinstance(metadata, dict) else None
        if not isinstance(command_run, dict):
            metadata["command_run"] = {
                "source_prefix": getattr(payload, "source_prefix", "/"),
                "original_text": getattr(payload, "original_text", ""),
            }

        host._msg_presenter.send(
            str(getattr(payload, "content", "") or "").strip(),
            [],
            metadata=metadata,
        )

    def _apply_document_updates(self, conversation, updates: dict[str, Any]) -> None:
        try:
            state = conversation.get_state()
        except Exception as exc:
            logger.debug("Failed to load state for prompt invocation updates: %s", exc)
            return

        changed = False
        current_seq = int(conversation.current_seq_id() or 0)
        for name, value in updates.items():
            doc_name = str(name or "").strip().lower()
            if not doc_name:
                continue
            doc = state.ensure_document(doc_name)
            next_content = str(value or "").strip()
            if doc.content == next_content:
                continue
            doc.content = next_content
            doc.updated_seq = current_seq
            changed = True

        if not changed:
            return

        try:
            state.last_updated_seq = current_seq
            conversation.set_state(state)
        except Exception as exc:
            logger.debug("Failed to persist prompt invocation document updates: %s", exc)

    def _append_info_message(self, content: str) -> None:
        host = self._host
        if not host.current_conversation:
            return
        info_msg = Message(role="assistant", content=content)
        host.current_conversation.messages.append(info_msg)
        host.chat_view.add_message(info_msg)
        host.services.conv_service.save(host.current_conversation)

    def _switch_mode(self, mode_slug: str, *, persist: bool = True) -> None:
        host = self._host
        normalized = str(mode_slug or "").strip().lower()
        if not normalized:
            return

        idx = host.input_area.mode_combo.findData(normalized)
        if idx < 0:
            self._append_info_message(f"Unknown mode: {normalized}")
            return

        try:
            host.input_area.mode_combo.blockSignals(True)
            host.input_area.mode_combo.setCurrentIndex(idx)
        finally:
            host.input_area.mode_combo.blockSignals(False)

        host.input_area.apply_mode_policy(apply_defaults=True)

        conversation = host.current_conversation
        if conversation is None:
            return

        try:
            conversation.mode = normalized
            if persist:
                host.services.conv_service.save(conversation)
        except Exception as exc:
            logger.debug("Failed to persist mode switch: %s", exc)

    def _run_shell_command(self, payload: ShellInvocation | None) -> None:
        host = self._host
        if payload is None:
            return

        if not host.current_conversation:
            self.new()
        conversation = host.current_conversation
        if conversation is None:
            return

        command_text = str(payload.command_text or "").strip()
        if not command_text:
            return

        display_command = str(payload.original_text or "").strip() or f"{payload.source_prefix}{command_text}"

        user_msg = Message(role="user", content=display_command)
        user_msg.metadata["explicit_shell"] = True
        conversation.add_message(user_msg)
        host.chat_view.add_message(user_msg)

        try:
            result_text = host.services.command_service.execute_shell_invocation(
                payload,
                work_dir=getattr(conversation, "work_dir", "") or ".",
                permission_policy=ToolPermissionPolicy.from_config(host._app_settings),
                approval_callback=self._ask_command_approval,
            )
            assistant_msg = Message(role="assistant", content=result_text)
            assistant_msg.metadata["explicit_shell_result"] = True
            assistant_msg.metadata["command"] = command_text
        except CommandExecutionDenied as exc:
            assistant_msg = Message(role="assistant", content=str(exc))
            assistant_msg.metadata["explicit_shell_result"] = True
            assistant_msg.metadata["command"] = command_text
            assistant_msg.metadata["denied"] = True
        except Exception as exc:
            assistant_msg = Message(role="assistant", content=f"Shell execution failed: {exc}")
            assistant_msg.metadata["explicit_shell_result"] = True
            assistant_msg.metadata["command"] = command_text
            assistant_msg.metadata["error"] = True

        conversation.add_message(assistant_msg)
        host.chat_view.add_message(assistant_msg)
        host.stats_panel.update_stats(conversation)
        host.services.conv_service.save(conversation)

        try:
            conversations = host.services.conv_service.list_all()
            host.sidebar.update_conversations(conversations)
            host.sidebar.select_conversation(conversation.id)
        except Exception as exc:
            logger.debug("Failed to refresh sidebar after explicit shell command: %s", exc)

    def _ask_command_approval(self, message: str) -> bool:
        reply = QMessageBox.question(
            self._host,
            "命令执行确认",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes
