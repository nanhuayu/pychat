from typing import List, Dict, Any
from models.state import SessionState, Task, TaskStatus, TaskPriority

class TaskService:
    @staticmethod
    def handle_ops(state: SessionState, ops: List[Dict[str, Any]], current_seq: int) -> List[str]:
        feedback = []
        for op in ops:
            action = op.get("action")
            
            if action == "create":
                content = op.get("content", "").strip()
                if not content:
                    feedback.append("⚠️ Skipped create: empty content")
                    continue
                    
                new_task = Task(
                    content=content,
                    status=TaskStatus(op.get("status", "pending")),
                    priority=TaskPriority(op.get("priority", "medium")),
                    tags=op.get("tags", []),
                    created_seq=current_seq,
                    updated_seq=current_seq
                )
                state.tasks.append(new_task)
                feedback.append(f"✅ Created task [{new_task.id}]: {content[:50]}")
                
            elif action == "update":
                task_id = op.get("id")
                if not task_id:
                    feedback.append("⚠️ Skipped update: missing task ID")
                    continue
                    
                task = state.find_task(task_id)
                if not task:
                    feedback.append(f"⚠️ Task [{task_id}] not found")
                    continue
                
                # Apply updates
                update_fields = {}
                if "content" in op: update_fields["content"] = op["content"]
                if "status" in op: update_fields["status"] = op["status"]
                if "priority" in op: update_fields["priority"] = op["priority"]
                if "tags" in op: update_fields["tags"] = op["tags"]
                
                task.update(current_seq, **update_fields)
                feedback.append(f"✅ Updated task [{task_id}]: {list(update_fields.keys())}")
                
            elif action == "delete":
                task_id = op.get("id")
                if not task_id:
                    feedback.append("⚠️ Skipped delete: missing task ID")
                    continue
                    
                original_len = len(state.tasks)
                state.tasks = [t for t in state.tasks if t.id != task_id]
                
                if len(state.tasks) < original_len:
                    feedback.append(f"✅ Deleted task [{task_id}]")
                else:
                    feedback.append(f"⚠️ Task [{task_id}] not found to delete")
                    
        return feedback
