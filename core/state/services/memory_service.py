from typing import Dict, Any, List
from models.state import SessionState

class MemoryService:
    @staticmethod
    def handle_updates(state: SessionState, updates: Dict[str, Any], current_seq: int) -> List[str]:
        feedback = []
        for key, value in updates.items():
            if value is None:
                # Delete key
                if key in state.memory:
                    del state.memory[key]
                    feedback.append(f"🗑️ Forgot: {key}")
            else:
                # Set/update key
                state.memory[key] = str(value)
                feedback.append(f"💾 Remembered: {key}")
        return feedback
