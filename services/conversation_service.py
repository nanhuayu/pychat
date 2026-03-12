"""Conversation lifecycle service.

Centralizes conversation CRUD and message operations that were
previously scattered across UI presenters and MainWindow.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from models.conversation import Conversation, Message
from services.storage_service import StorageService

logger = logging.getLogger(__name__)


class ConversationService:
    """Manages conversation persistence and message operations."""

    def __init__(self, storage: StorageService) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Conversation CRUD
    # ------------------------------------------------------------------

    def create(self, title: str | None = None) -> Conversation:
        conv = Conversation()
        if title:
            conv.title = title
        return conv

    def load(self, conversation_id: str) -> Optional[Conversation]:
        return self._storage.load_conversation(conversation_id)

    def list_all(self) -> List[Dict[str, Any]]:
        return self._storage.list_conversations()

    def save(self, conversation: Conversation) -> bool:
        return self._storage.save_conversation(conversation)

    def delete(self, conversation_id: str) -> bool:
        return self._storage.delete_conversation(conversation_id)

    def import_from_file(self, file_path: str) -> Optional[Conversation]:
        return self._storage.import_conversation(file_path)

    def duplicate(self, source: Conversation) -> Conversation:
        """Create a deep copy with a new ID and timestamp."""
        dup = Conversation.from_dict(source.to_dict())
        dup.id = str(uuid.uuid4())
        now = datetime.now()
        dup.created_at = now
        dup.updated_at = now
        base_title = (source.title or "New Chat").strip() or "New Chat"
        dup.title = f"{base_title}（副本）"
        return dup

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    def add_message(
        self, conversation: Conversation, message: Message, *, auto_save: bool = False,
    ) -> None:
        conversation.add_message(message)
        if auto_save:
            self.save(conversation)

    def delete_messages(self, conversation: Conversation, message_id: str) -> list[str]:
        return conversation.delete_message(message_id) or []

    def find_message(self, conversation: Conversation, message_id: str) -> Optional[Message]:
        for msg in conversation.messages:
            if msg.id == message_id:
                return msg
        return None

    def ensure_title(self, conversation: Conversation) -> None:
        """Auto-generate a title from the first message if needed."""
        if len(conversation.messages) == 1:
            conversation.generate_title_from_first_message()

    # ------------------------------------------------------------------
    # Provider helpers
    # ------------------------------------------------------------------

    @staticmethod
    def find_provider(providers: list, provider_id: str):
        for p in providers:
            if p.id == provider_id:
                return p
        return None
