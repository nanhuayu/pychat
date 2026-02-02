from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import time

@dataclass
class AgentTask:
    """Represents a running agent task loop."""
    task_id: str
    description: str
    created_at: float = field(default_factory=time.time)
    
    # State shared across tool calls (memory, plan)
    state: Dict[str, Any] = field(default_factory=dict)
    
    # Execution history
    history: List[Dict[str, Any]] = field(default_factory=list)
    
    status: str = "running" # running, completed, failed, paused
    total_cost: float = 0.0

    def update_cost(self, cost: float):
        self.total_cost += cost

    def add_history(self, entry: Dict[str, Any]):
        self.history.append(entry)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize task to dict."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "created_at": self.created_at,
            "state": self.state,
            "history": self.history,
            "status": self.status,
            "total_cost": self.total_cost
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentTask':
        """Deserialize task from dict."""
        task = cls(
            task_id=data.get("task_id", ""),
            description=data.get("description", "")
        )
        task.created_at = data.get("created_at", time.time())
        task.state = data.get("state", {})
        task.history = data.get("history", [])
        task.status = data.get("status", "running")
        task.total_cost = data.get("total_cost", 0.0)
        return task

