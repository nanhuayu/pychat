import asyncio
import uuid
import json
import os
import time
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from models.conversation import Conversation, Message
from models.provider import Provider
from services.chat_service import ChatService
from services.mcp_manager import McpManager
from core.agent.task import AgentTask
from core.tools.base import ToolContext

class AgentRunner:
    """Executes the Agent Think-Act Loop."""
    
    def __init__(self, chat_service: ChatService, mcp_manager: McpManager, persistence_dir: str = "tasks"):
        self.chat_service = chat_service
        self.mcp_manager = mcp_manager
        self.max_turns = 20
        self.persistence_dir = Path(persistence_dir)
        self.persistence_dir.mkdir(parents=True, exist_ok=True)

    def _save_task(self, task: AgentTask):
        try:
            file_path = self.persistence_dir / f"task_{task.task_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save task: {e}")

    def _prune_history(self, history: List[Dict[str, Any]], max_tokens: int = 100000) -> List[Dict[str, Any]]:
        # Simple heuristic: Keep last N messages. 
        # Roo Code does sliding window token counting. 
        # For now, let's keep last 50 entries to avoid context overflow in simple cases.
        # Ideally, we should count tokens.
        if len(history) > 50:
            return history[-50:]
        return history

    async def run_task(
        self,
        provider: Provider,
        conversation: Conversation,
        task_description: str,
        on_update: Optional[Callable[[str], None]] = None,
        approval_callback: Optional[Callable[[str], bool]] = None,
        resume_task_id: Optional[str] = None
    ) -> AgentTask:
        """
        Run a task loop.
        """
        if resume_task_id:
            # Try to load existing task
            try:
                file_path = self.persistence_dir / f"task_{resume_task_id}.json"
                if file_path.exists():
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        task = AgentTask.from_dict(data)
                        if on_update: on_update(f"Resuming task {task.task_id}")
                else:
                    raise FileNotFoundError(f"Task {resume_task_id} not found")
            except Exception as e:
                if on_update: on_update(f"Failed to resume task: {e}. Starting new one.")
                task = AgentTask(task_id=str(uuid.uuid4()), description=task_description)
        else:
            task = AgentTask(
                task_id=str(uuid.uuid4()),
                description=task_description
            )
        
        self._save_task(task)

        turn_count = 0
        
        while turn_count < self.max_turns and task.status == "running":
            turn_count += 1
            if on_update:
                on_update(f"--- Turn {turn_count} ---")

            # 1. Call LLM
            # Prune conversation messages if too long?
            # ChatService builds messages from 'conversation'. We should ensure conversation syncs with task history.
            # But task.history is raw dicts. Conversation.messages is Message objects.
            # We assume conversation is kept up to date by this loop.
            
            # TODO: Implement context window management on 'conversation' object here if needed.
            # For now, rely on ChatService not crashing.

            try:
                response_msg = await self.chat_service.send_message(
                    provider=provider,
                    conversation=conversation,
                    enable_thinking=True,
                    enable_search=True,
                    enable_mcp=True,
                    on_token=None 
                )
            except Exception as e:
                if on_update: on_update(f"LLM Error: {e}")
                break
            
            # Append Assistant Response
            conversation.messages.append(response_msg)
            task.add_history({"role": "assistant", "content": response_msg.content, "tool_calls": response_msg.tool_calls})
            self._save_task(task)

            # Check if done
            if not response_msg.tool_calls:
                if on_update:
                    on_update("Agent finished (no tool calls).")
                task.status = "completed"
                self._save_task(task)
                break

            # 2. Execute Tools
            tool_outputs = []
            for tool_call in response_msg.tool_calls:
                func_name = tool_call.get("function", {}).get("name")
                args_str = tool_call.get("function", {}).get("arguments", "{}")
                call_id = tool_call.get("id")
                
                if on_update:
                    on_update(f"Executing tool: {func_name}")

                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}

                # Context with shared state
                context = ToolContext(
                    work_dir=self.mcp_manager._workspace_root,
                    approval_callback=approval_callback,
                    state=task.state
                )
                
                result_str = await self.mcp_manager.execute_tool_with_context(
                    tool_name=func_name,
                    arguments=args,
                    context=context
                )
                
                tool_outputs.append({
                    "tool_call_id": call_id,
                    "role": "tool",
                    "name": func_name,
                    "content": result_str
                })
                
                if on_update:
                    on_update(f"Tool Result: {result_str[:200]}...")

            # 3. Append Tool Outputs
            for output in tool_outputs:
                conversation.messages.append(Message(
                    role="tool",
                    content=output["content"],
                    tool_call_id=output["tool_call_id"],
                    name=output["name"]
                ))
                task.add_history(output)
            
            self._save_task(task)
            
        return task
