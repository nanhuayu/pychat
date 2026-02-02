
import asyncio
import json
import uuid
from typing import List, Optional, Callable, Dict, Any, Union

from models.conversation import Conversation, Message
from models.provider import Provider
from services.chat_service import ChatService
from services.mcp_manager import McpManager
from core.tools.base import ToolContext

class Task:
    """
    Manages a "Think-Act" loop for an Agent.
    Executes multiple turns of conversation until the task is completed or stopped.
    """
    def __init__(self, 
                 conversation: Conversation, 
                 provider: Provider, 
                 chat_service: ChatService, 
                 mcp_manager: McpManager,
                 max_loops: int = 20,
                 enable_search: bool = False,
                 enable_mcp: bool = True):
        self.conversation = conversation
        self.provider = provider
        self.chat_service = chat_service
        self.mcp_manager = mcp_manager
        self.max_loops = max_loops
        self.enable_search = enable_search
        self.enable_mcp = enable_mcp
        self.current_loop = 0
        self.status = "pending"
        self._cancel_event = asyncio.Event()
        self.task_id = str(uuid.uuid4())
        self.consecutive_mistake_count = 0

    def cancel(self):
        """Request task cancellation."""
        self._cancel_event.set()

    async def run(self, 
                  on_token: Optional[Callable[[str], None]] = None,
                  on_thinking: Optional[Callable[[str], None]] = None,
                  on_step: Optional[Callable[[Message], None]] = None) -> None:
        """
        Execute the task loop.
        
        Args:
            on_token: Callback for streaming tokens.
            on_thinking: Callback for streaming thinking content.
            on_step: Callback when a message (assistant response or tool result) is added.
        """
        self.status = "running"
        self.current_loop = 0
        
        try:
            while self.current_loop < self.max_loops:
                if self._cancel_event.is_set():
                    self.status = "cancelled"
                    break
                    
                self.current_loop += 1
                
                # 1. Send request to LLM
                # We use the ChatService to handle the API call and parsing
                # Note: We assume the conversation history is already up-to-date in self.conversation
                response_msg = await self.chat_service.send_message(
                    self.provider,
                    self.conversation,
                    on_token=on_token,
                    on_thinking=on_thinking,
                    enable_search=self.enable_search,
                    enable_mcp=self.enable_mcp,
                    cancel_event=self._cancel_event
                )
                
                # Notify step (assistant response)
                if on_step:
                    on_step(response_msg)
                
                # Add assistant message to conversation
                # Note: ChatService returns a Message object but doesn't add it to conversation automatically
                self.conversation.add_message(response_msg)
                
                # 2. Check for tool calls
                if not response_msg.tool_calls:
                    self.status = "completed"
                    # No tools called, task is done (for this turn)
                    return
                
                # 3. Execute tools
                # We execute all tool calls in sequence (or parallel if possible, but sequence is safer for state)
                for tool_call in response_msg.tool_calls:
                    if self._cancel_event.is_set():
                        self.status = "cancelled"
                        return

                    # Handle OpenAI format
                    if "function" in tool_call:
                        tool_name = tool_call.get("function", {}).get("name")
                        tool_args = tool_call.get("function", {}).get("arguments", "{}")
                    else:
                        # Handle flat format (if any)
                        tool_name = tool_call.get("name")
                        tool_args = tool_call.get("arguments", {})
                        
                    # Ensure tool_args is a dict
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except:
                            pass
                            
                    call_id = tool_call.get("id")
                    
                    # Create context
                    # The approval_callback here is a fallback. 
                    # McpManager should handle auto-approvals based on its config.
                    # If manual approval is needed, McpManager will call this callback.
                    # TODO: Connect to UI for manual approval
                    async def ui_approval_callback(msg: str) -> bool:
                        # Placeholder: In a real app, this would emit a signal to UI to show a dialog
                        # and await the user's response.
                        print(f"Requesting manual approval for: {msg}")
                        return False 
                    
                    context = ToolContext(
                        work_dir=self.conversation.work_dir or ".",
                        approval_callback=ui_approval_callback
                    )
                    
                    result_str = ""
                    try:
                        result_str = await self.mcp_manager.execute_tool_with_context(
                            tool_name, 
                            tool_args, 
                            context
                        )
                        self.consecutive_mistake_count = 0
                    except Exception as e:
                        result_str = f"Error executing tool {tool_name}: {str(e)}"
                        self.consecutive_mistake_count += 1
                        
                    if self.consecutive_mistake_count >= 3:
                        result_str += "\n\n[System] Too many consecutive errors. Stopping task."
                        self.status = "failed_too_many_errors"
                        self._cancel_event.set()
                    
                    # Create tool result message
                    tool_msg = Message(
                        role="tool",
                        content=result_str,
                        tool_call_id=call_id,
                        metadata={"name": tool_name}
                    )
                    
                    self.conversation.add_message(tool_msg)
                    
                    # Notify step (tool result)
                    if on_step:
                        on_step(tool_msg)
            
            if self.current_loop >= self.max_loops:
                self.status = "max_loops_exceeded"
                
        except Exception as e:
            self.status = "failed"
            # Log error
            print(f"Task execution failed: {e}")
            raise e
