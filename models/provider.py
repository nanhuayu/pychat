"""
LLM Provider configuration model
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
import uuid
import json


@dataclass
class Provider:
    """Represents an LLM provider configuration"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "New Provider"
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    models: List[str] = field(default_factory=list)
    default_model: str = ""
    custom_headers: Dict[str, str] = field(default_factory=dict)
    request_format: Dict[str, Any] = field(default_factory=dict)
    supports_thinking: bool = False
    supports_vision: bool = True
    max_tokens: int = 4096
    temperature: float = 0.7
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'name': self.name,
            'api_base': self.api_base,
            'api_key': self.api_key,
            'models': self.models,
            'default_model': self.default_model,
            'custom_headers': self.custom_headers,
            'request_format': self.request_format,
            'supports_thinking': self.supports_thinking,
            'supports_vision': self.supports_vision,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'enabled': self.enabled
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Provider':
        """Create from dictionary"""
        return cls(
            id=data.get('id', str(uuid.uuid4())),
            name=data.get('name', 'Provider'),
            api_base=data.get('api_base', 'https://api.openai.com/v1'),
            api_key=data.get('api_key', ''),
            models=data.get('models', []),
            default_model=data.get('default_model', ''),
            custom_headers=data.get('custom_headers', {}),
            request_format=data.get('request_format', {}),
            supports_thinking=data.get('supports_thinking', False),
            supports_vision=data.get('supports_vision', True),
            max_tokens=data.get('max_tokens', 4096),
            temperature=data.get('temperature', 0.7),
            enabled=data.get('enabled', True)
        )

    def to_json(self) -> str:
        """Serialize to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> 'Provider':
        """Create from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def get_headers(self) -> Dict[str, str]:
        """Get complete headers for API requests"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        headers.update(self.custom_headers)
        return headers

    def get_chat_endpoint(self) -> str:
        """Get the chat completions endpoint"""
        base = self.api_base.rstrip('/')
        return f"{base}/chat/completions"

    def get_models_endpoint(self) -> str:
        """Get the models list endpoint"""
        base = self.api_base.rstrip('/')
        return f"{base}/models"
