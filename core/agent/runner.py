import asyncio
import uuid
import json
import os
import time
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Union

from models.conversation import Conversation, Message
from models.provider import Provider
from core.llm.client import LLMClient
from core.tools.manager import McpManager
from core.agent.task import AgentTask
from core.tools.base import ToolContext
from core.condense.condenser import ContextCondenser
from core.llm.token_utils import estimate_conversation_tokens

class AgentRunner:
    """
    Executes the Agent Think-Act Loop.
    Unifies Chat Mode and Agent Mode execution.
    Handles per-message condensation and context management.
    """
    
    def __init__(self, 
                 client: LLMClient, 
                 mcp_manager: McpManager, 
                 persistence_dir: str = "tasks",
                 context_window_limit: int = 100000):
        self.client = client
        self.mcp_manager = mcp_manager
        self.persistence_dir = Path(persistence_dir)
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
        self.context_window_limit = context_window_limit
        self.condenser = ContextCondenser(client)

    def _save_task(self, task: AgentTask):
        try:
            file_path = self.persistence_dir / f"task_{task.task_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to save task: {e}")

    async def _manage_context(self, conversation: Conversation, provider: Provider):
        """
        Check token count and condense conversation if needed.
        Also triggers per-message condensation for recent heavy messages.
        """
        # 1. Per-message condensation (More aggressive now)
        # We look at recent messages to condense tool outputs and long assistant responses
        
        messages = conversation.messages
        # Only check last 20 messages to save time, but exclude the very last one (current)
        start_idx = max(0, len(messages) - 20)
        end_idx = max(0, len(messages) - 1) 
        
        for i in range(end_idx - 1, start_idx - 1, -1):
            msg = messages[i]
            if msg.summary:
                continue
                
            should_condense = False
            
            # Condense Tool Results (often verbose)
            if msg.role == "tool":
                # Always condense tool results unless very short
                if msg.content and len(msg.content) > 200:
                    should_condense = True
            
            # Condense Assistant Responses if long
            elif msg.role == "assistant":
                if msg.content and len(msg.content) > 800:
                    should_condense = True
            
            if should_condense:
                # Async condensation
                await self.condenser.condense_message(msg, provider)

        # 2. Global condensation (Context Window)
        current_tokens = estimate_conversation_tokens(conversation)
        
        active_messages_count = len([m for m in conversation.messages if not m.condense_parent and not m.truncation_parent and m.role != "system"])

        threshold = self.context_window_limit * 0.7 
        
        if active_messages_count > 20 or current_tokens > threshold:
            print(f"[AgentRunner] Triggering safety condensation. Active msgs: {active_messages_count}, Tokens: {current_tokens}")
            await self.condenser.condense(conversation, provider, keep_last_n=10)

    async def run_task(
        self,
        provider: Provider,
        conversation: Conversation,
        task_description: str,
        max_turns: int = 20,
        enable_thinking: bool = True,
        enable_search: bool = True,
        enable_mcp: bool = True,
        on_update: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
        on_step: Optional[Callable[[Message], None]] = None,
        approval_callback: Optional[Callable[[str], bool]] = None,
        resume_task_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None
    ) -> AgentTask:
        """
        Run a task loop.
        
        Args:
            on_token: Callback for streaming tokens.
            on_thinking: Callback for streaming thinking content.
            on_step: Callback when a message (assistant response or tool result) is added.
        """
        # 1. Initialize or Load Task
        if resume_task_id:
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
        consecutive_mistake_count = 0
        
        while turn_count < max_turns and task.status == "running":
            if cancel_event and cancel_event.is_set():
                task.status = "cancelled"
                break

            turn_count += 1
            if on_update:
                on_update(f"--- Turn {turn_count} ---")

            # 2. Manage Context (Condensation)
            await self._manage_context(conversation, provider)

            # 3. Call LLM
            try:
                response_msg = await self.client.send_message(
                    provider=provider,
                    conversation=conversation,
                    enable_thinking=bool(enable_thinking),
                    enable_search=bool(enable_search),
                    enable_mcp=bool(enable_mcp),
                    on_token=on_token,
                    on_thinking=on_thinking,
                    cancel_event=cancel_event
                )
            except Exception as e:
                if on_update: on_update(f"LLM Error: {e}")
                task.status = "failed"
                break
            
            # Notify step (assistant response)
            if on_step:
                on_step(response_msg)

            # Append Assistant Response
            conversation.messages.append(response_msg)
            task.add_history({"role": "assistant", "content": response_msg.content, "tool_calls": response_msg.tool_calls})
            self._save_task(task)

            # Check if done
            if not response_msg.tool_calls:
                if on_update:
                    on_update("Agent finished (no tool calls).")
                await self.condenser.summarize_last_session(conversation, provider)
                active_messages_count = len(
                    [m for m in conversation.messages if not m.condense_parent and not m.truncation_parent and m.role != "system"]
                )
                if active_messages_count > 12:
                    await self.condenser.condense(conversation, provider, keep_last_n=10)
                task.status = "completed"
                self._save_task(task)
                break

            # 4. Execute Tools
            tool_outputs = []
            for tool_call in response_msg.tool_calls:
                if cancel_event and cancel_event.is_set():
                    task.status = "cancelled"
                    break

                func_name = tool_call.get("function", {}).get("name")
                args_str = tool_call.get("function", {}).get("arguments", "{}")
                call_id = tool_call.get("id")
                
                if on_update:
                    on_update(f"Executing tool: {func_name}")

                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}

                allowed = False
                if isinstance(func_name, str) and func_name:
                    if func_name == "builtin_web_search":
                        allowed = bool(enable_search)
                    elif func_name.startswith("mcp__"):
                        allowed = bool(enable_mcp)
                    else:
                        allowed = bool(enable_mcp)

                # Context with shared state
                # Use conversation's work_dir if available, otherwise default to manager's root
                work_dir = getattr(conversation, "work_dir", None) or self.mcp_manager._workspace_root
                
                context = ToolContext(
                    work_dir=work_dir,
                    approval_callback=approval_callback,
                    state=task.state
                )
                
                try:
                    if not allowed:
                        result_str = f"Tool disabled: {func_name}"
                    else:
                        result_str = await self.mcp_manager.execute_tool_with_context(
                            tool_name=func_name,
                            arguments=args,
                            context=context
                        )
                        consecutive_mistake_count = 0
                except Exception as e:
                    result_str = f"Error executing tool {func_name}: {str(e)}"
                    consecutive_mistake_count += 1
                
                tool_outputs.append({
                    "tool_call_id": call_id,
                    "role": "tool",
                    "name": func_name,
                    "content": result_str
                })
                
                if on_update:
                    on_update(f"Tool Result: {result_str[:200]}...")
            
            # Check for too many errors
            if consecutive_mistake_count >= 3:
                if on_update: on_update("Too many consecutive errors. Stopping task.")
                task.status = "failed"
                self._save_task(task)
                break

            # 5. Append Tool Outputs
            for output in tool_outputs:
                msg = Message(
                    role="tool",
                    content=output["content"],
                    tool_call_id=output["tool_call_id"],
                )
                msg.name = output["name"]
                
                if on_step:
                    on_step(msg)

                conversation.add_message(msg)
                task.add_history(output)
            
            self._save_task(task)
            
        return task
