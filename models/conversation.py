"""
Conversation and Message data models
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid
import json


@dataclass
class Message:
    """Represents a single message in a conversation"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: str = "user"  # "user", "assistant", "system"
    content: str = ""
    images: List[str] = field(default_factory=list)  # Base64 or file paths
    tool_calls: Optional[List[Dict[str, Any]]] = None  # [{id, type, function: {name, arguments}}]
    tool_call_id: Optional[str] = None  # For role="tool" messages
    thinking: Optional[str] = None
    tokens: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    response_time_ms: Optional[int] = None  # Response time in milliseconds
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'images': self.images,
            'tool_calls': self.tool_calls,
            'tool_call_id': self.tool_call_id,
            'thinking': self.thinking,
            'tokens': self.tokens,
            'created_at': self.created_at.isoformat(),
            'response_time_ms': self.response_time_ms,
            'metadata': self.metadata
        }

    @staticmethod
    def _normalize_content_and_images(
        raw_content: Any,
        existing_images: Any,
        existing_metadata: Any
    ) -> tuple[str, List[str], Dict[str, Any]]:
        images: List[str] = []
        if isinstance(existing_images, list):
            images.extend([i for i in existing_images if isinstance(i, str) and i])
        elif isinstance(existing_images, str) and existing_images:
            images.append(existing_images)

        metadata: Dict[str, Any] = {}
        if isinstance(existing_metadata, dict):
            metadata.update(existing_metadata)

        # OpenAI/多模态格式：content=[{"type":"text","text":"..."},{"type":"image_url","image_url":{"url":"data:..."}}]
        if isinstance(raw_content, list):
            text_parts: List[str] = []
            for part in raw_content:
                if isinstance(part, str):
                    if part:
                        text_parts.append(part)
                    continue

                if not isinstance(part, dict):
                    continue

                part_type = part.get('type')
                if part_type == 'text':
                    text = part.get('text')
                    if isinstance(text, str) and text:
                        text_parts.append(text)
                elif part_type == 'image_url':
                    image_url = part.get('image_url', {})
                    url = None
                    if isinstance(image_url, dict):
                        url = image_url.get('url')
                    if isinstance(url, str) and url:
                        images.append(url)

            # 保留原始结构，方便将来再导出为 payload
            metadata.setdefault('raw_content', raw_content)
            return ('\n'.join(text_parts)).strip(), images, metadata

        # ChatGPT 导出格式：content={"parts":["..."]}
        if isinstance(raw_content, dict):
            parts = raw_content.get('parts')
            if isinstance(parts, list):
                text = '\n'.join(str(p) for p in parts if isinstance(p, (str, int, float)))
                metadata.setdefault('raw_content', raw_content)
                return text.strip(), images, metadata

        # 兜底：保证 content 为字符串
        if raw_content is None:
            return '', images, metadata
        if isinstance(raw_content, str):
            return raw_content, images, metadata
        return str(raw_content), images, metadata

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Create from dictionary"""
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()

        content, images, metadata = cls._normalize_content_and_images(
            data.get('content', ''),
            data.get('images', []),
            data.get('metadata', {})
        )
            
        return cls(
            id=data.get('id', str(uuid.uuid4())),
            role=data.get('role', 'user'),
            content=content,
            images=images,
            tool_calls=data.get('tool_calls'),
            tool_call_id=data.get('tool_call_id'),
            thinking=data.get('thinking'),
            tokens=data.get('tokens'),
            created_at=created_at,
            response_time_ms=data.get('response_time_ms'),
            metadata=metadata
        )


@dataclass
class Conversation:
    """Represents a chat conversation"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "New Chat"
    messages: List[Message] = field(default_factory=list)
    provider_id: str = ""
    model: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    total_tokens: int = 0
    work_dir: str = ""  # Associated workspace directory
    settings: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'title': self.title,
            'messages': [msg.to_dict() for msg in self.messages],
            'provider_id': self.provider_id,
            'model': self.model,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'total_tokens': self.total_tokens,
            'work_dir': self.work_dir,
            'settings': self.settings
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Conversation':
        """Create from dictionary"""
        messages = [Message.from_dict(m) for m in data.get('messages', [])]
        
        created_at = data.get('created_at')
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()
            
        updated_at = data.get('updated_at')
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now()
            
        return cls(
            id=data.get('id', str(uuid.uuid4())),
            title=data.get('title', 'Imported Chat'),
            messages=messages,
            provider_id=data.get('provider_id', ''),
            model=data.get('model', ''),
            created_at=created_at,
            updated_at=updated_at,
            total_tokens=data.get('total_tokens', 0),
            work_dir=data.get('work_dir', ''),
            settings=data.get('settings', {})
        )

    def to_json(self) -> str:
        """Serialize to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> 'Conversation':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def add_message(self, message: Message):
        """Add a message to the conversation.
           If the message is a tool result (role='tool'), try to merge it into the existing assistant message.
        """
        if message.role == 'tool' and message.tool_call_id:
            if self._try_merge_tool_result(message):
                return

        # Normal append
        self.messages.append(message)
        if message.tokens:
            self.total_tokens += message.tokens
        self.updated_at = datetime.now()

    def _try_merge_tool_result(self, message: Message) -> bool:
        """Try to find the assistant message that triggered this tool result and merge it."""
        # Search backwards for the assistant message containing the tool call
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            if msg.role == 'assistant' and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get('id') == message.tool_call_id:
                        tc['result'] = message.content
                        self.updated_at = datetime.now()
                        return True
        return False

    def update_message(self, message_id: str, content: str = None, 
                       images: List[str] = None):
        """Update an existing message"""
        for msg in self.messages:
            if msg.id == message_id:
                if content is not None:
                    msg.content = content
                if images is not None:
                    msg.images = images
                self.updated_at = datetime.now()
                break

    def delete_message(self, message_id: str) -> List[str]:
        """Delete a message from the conversation.
           Returns a list containing the deleted message ID.
           Note: If we were storing tool results as separate messages, we would need to cascade delete them here.
           But since we merge tool results into the assistant message, deleting the assistant message
           implicitly deletes the results.
        """
        original_count = len(self.messages)
        self.messages = [m for m in self.messages if m.id != message_id]
        
        if len(self.messages) < original_count:
            self.updated_at = datetime.now()
            return [message_id]
        return []

    def get_tokens_per_minute(self) -> float:
        """Calculate average tokens per minute for assistant responses"""
        total_tokens = 0
        total_time_ms = 0
        
        for msg in self.messages:
            if msg.role == 'assistant' and msg.tokens and msg.response_time_ms:
                total_tokens += msg.tokens
                total_time_ms += msg.response_time_ms
        
        if total_time_ms > 0:
            return (total_tokens / total_time_ms) * 60000  # Convert to per minute
        return 0.0

    def generate_title_from_first_message(self):
        """Generate title from first user message"""
        for msg in self.messages:
            if msg.role == 'user' and msg.content:
                # Take first 50 characters
                title = msg.content[:50]
                if len(msg.content) > 50:
                    title += "..."
                self.title = title
                break
