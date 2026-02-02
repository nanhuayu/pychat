
from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class TaskResult:
    status: TaskStatus
    message: str
    data: Optional[Dict[str, Any]] = None
