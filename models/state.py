"""
SessionState: Centralized state management for conversations.

This module implements the "State-Driven + Event-Sourcing Lite" architecture:
- SessionState holds summary/tasks/memory as structured data (not scattered in messages)
- All state changes are tracked via seq_id for rollback/time-travel
- Tools write to state explicitly via StateManagerTool
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import uuid
import copy
from datetime import datetime


class TaskStatus(str, Enum):
    """Task lifecycle states"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Task priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class Task:
    """
    A structured task/todo item with full metadata.
    
    Attributes:
        id: Unique identifier (auto-generated short UUID)
        content: Task description
        status: Current lifecycle state
        priority: Importance level
        tags: Categorization labels
        created_seq: The seq_id when this task was created
        updated_seq: The seq_id when this task was last modified
    """
    content: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    tags: List[str] = field(default_factory=list)
    created_seq: int = 0
    updated_seq: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'content': self.content,
            'status': self.status.value,
            'priority': self.priority.value,
            'tags': self.tags,
            'created_seq': self.created_seq,
            'updated_seq': self.updated_seq
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        return cls(
            id=data.get('id', str(uuid.uuid4())[:8]),
            content=data.get('content', ''),
            status=TaskStatus(data.get('status', 'pending')),
            priority=TaskPriority(data.get('priority', 'medium')),
            tags=data.get('tags', []),
            created_seq=data.get('created_seq', 0),
            updated_seq=data.get('updated_seq', 0)
        )

    def update(self, current_seq: int, **kwargs):
        """Update task fields and bump updated_seq"""
        for key, value in kwargs.items():
            if value is None:
                continue
            if key == 'status':
                self.status = TaskStatus(value) if isinstance(value, str) else value
            elif key == 'priority':
                self.priority = TaskPriority(value) if isinstance(value, str) else value
            elif hasattr(self, key):
                setattr(self, key, value)
        self.updated_seq = current_seq


@dataclass
class SessionState:
    """
    The "brain" of a conversation - holds cognitive state separate from message history.
    
    This replaces the scattered condense_parent/summary fields with a unified state object.
    Key design decisions:
    - summary: Global rolling summary (replaces is_summary messages)
    - tasks: Structured todo list with full lifecycle (replaces markdown parsing)
    - memory: Key-value long-term facts (user preferences, important paths, etc.)
    - last_updated_seq: Tracks when state was last modified for rollback
    
    The state is:
    1. Persisted as part of Conversation JSON
    2. Injected into System Prompt for LLM context
    3. Updated via explicit tool calls (StateManagerTool)
    """
    summary: str = ""
    tasks: List[Task] = field(default_factory=list)
    memory: Dict[str, str] = field(default_factory=dict)
    archived_summaries: List[str] = field(default_factory=list)
    last_updated_seq: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'summary': self.summary,
            'tasks': [t.to_dict() for t in self.tasks],
            'memory': self.memory,
            'last_updated_seq': self.last_updated_seq
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionState':
        if not data:
            return cls()
        tasks = [Task.from_dict(t) for t in data.get('tasks', [])]
        return cls(
            summary=data.get('summary', ''),
            tasks=tasks,
            memory=data.get('memory', {}),
            last_updated_seq=data.get('last_updated_seq', 0)
        )

    def create_snapshot(self) -> 'SessionState':
        """Create a deep copy for rollback support"""
        return copy.deepcopy(self)

    def get_active_tasks(self) -> List[Task]:
        """Get non-completed/cancelled tasks"""
        return [t for t in self.tasks if t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)]

    def find_task(self, task_id: str) -> Optional[Task]:
        """Find task by ID"""
        return next((t for t in self.tasks if t.id == task_id), None)

    def to_prompt_view(self) -> str:
        """
        Render state as Markdown for System Prompt injection.
        
        This provides the LLM with current cognitive context without
        including full message history.
        """
        blocks = []
        
        # 1. Summary section
        if self.summary:
            blocks.append(f"### 📋 Context Summary\n{self.summary}")
        
        # 2. Active tasks section
        active_tasks = self.get_active_tasks()
        if active_tasks:
            task_lines = ["### ✅ Active Tasks"]
            for t in active_tasks:
                # Format: - [pending] (high) Task content #tag1 #tag2 [id:abc123]
                status_icon = "⏳" if t.status == TaskStatus.IN_PROGRESS else "⬜"
                priority_str = f"({t.priority.value})" if t.priority != TaskPriority.MEDIUM else ""
                tags_str = " ".join([f"#{tag}" for tag in t.tags]) if t.tags else ""
                task_lines.append(f"- {status_icon} {priority_str} {t.content} {tags_str} [id:{t.id}]")
            blocks.append("\n".join(task_lines))
        
        # 3. Memory section (key facts)
        if self.memory:
            mem_lines = ["### 💾 Remembered Facts"]
            for key, value in self.memory.items():
                # Truncate long values
                display_value = value[:100] + "..." if len(value) > 100 else value
                mem_lines.append(f"- **{key}**: {display_value}")
            blocks.append("\n".join(mem_lines))
        
        if not blocks:
            return ""
        
        header = "## 🧠 SESSION STATE\n_Use `manage_state` tool to update this when context changes._\n"
        return header + "\n\n".join(blocks)
