from typing import List, Dict, Any, Optional
from models.conversation import Conversation, Message
from models.provider import Provider
from utils.file_context import get_file_tree
import os
import platform

class PromptManager:
    """
    Centralized manager for system prompts and context assembly.
    """
    
    def __init__(self, work_dir: str = "."):
        self.work_dir = work_dir

    def get_system_prompt(self, 
                          conversation: Conversation, 
                          tools: List[Dict[str, Any]], 
                          provider: Provider) -> str:
        """
        Generates the dynamic system prompt.
        """
        # Base Role Definition
        role_def = """You are Roo, a highly skilled software engineer with extensive knowledge in many programming languages, frameworks, design patterns, and best practices.

You are running in a local environment (Agent Mode).
You have access to a set of tools to explore the codebase, read files, edit files, and run commands.
"""

        # Tool Usage Guidelines (Simplified for now)
        tool_guidelines = """
## Tool Usage
- You must use the provided tools to interact with the system.
- Always check the output of your commands.
- If a tool fails, analyze the error and try a different approach.
"""

        # Environment Info
        env_info = self._get_environment_section()
        
        # Custom Instructions (from settings)
        custom_instructions = conversation.settings.get("custom_instructions", "")
        
        # Combine
        prompt = f"{role_def}\n\n{tool_guidelines}\n\n{env_info}"
        
        if custom_instructions:
            prompt += f"\n\n## Custom Instructions\n{custom_instructions}"
            
        return prompt

    def _get_environment_section(self) -> str:
        os_info = platform.system() + " " + platform.release()
        file_tree = get_file_tree(self.work_dir, max_depth=2)
        
        return f"""## Environment
- Operating System: {os_info}
- Working Directory: {self.work_dir}
- File Tree (Top Level):
```
{file_tree}
```
"""

    def get_effective_history(self, messages: List[Message]) -> List[Message]:
        """
        Filters out messages that have been condensed or truncated.
        This implements the "Fresh Start" view for the LLM.
        """
        # Find the last summary
        last_summary_index = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].metadata.get("is_summary"):
                last_summary_index = i
                break
        
        def is_active(m: Message) -> bool:
            return not m.condense_parent and not m.truncation_parent

        def sanitize_tool_orphans(seq: List[Message]) -> List[Message]:
            sanitized: List[Message] = []
            for m in seq:
                if m.role == "tool":
                    prev = sanitized[-1] if sanitized else None
                    if not prev or prev.role != "assistant":
                        sanitized.append(
                            Message(
                                role="user",
                                content=f"Tool Output (Context Lost):\n{m.content}",
                                tool_call_id=m.tool_call_id,
                            )
                        )
                        continue
                sanitized.append(m)
            return sanitized

        if last_summary_index == -1:
            active = [m for m in messages if is_active(m)]
            return sanitize_tool_orphans(active)
            
        # If summary exists, return [Summary, ...Active Messages after Summary]
        # We also need to keep the System Prompt (usually index 0)
        
        effective_history = []
        
        # 1. System Prompt (if present at 0)
        if messages and messages[0].role == "system":
            effective_history.append(messages[0])
            
        # 2. Summary
        effective_history.append(messages[last_summary_index])
        
        # 3. Active messages AFTER summary
        tail_active: List[Message] = []
        for i in range(last_summary_index + 1, len(messages)):
            msg = messages[i]
            if is_active(msg):
                tail_active.append(msg)

        effective_history.extend(sanitize_tool_orphans(tail_active))
                
        return effective_history

    def apply_context_window(self, messages: List[Message], max_messages: int) -> List[Message]:
        if max_messages <= 0 or len(messages) <= max_messages:
            return messages

        pinned: List[Message] = []
        start = 0
        if messages and messages[0].role == "system":
            pinned.append(messages[0])
            start = 1

        summary_index = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].metadata.get("is_summary"):
                summary_index = i
                break

        rest = messages[start:]
        if summary_index >= 0:
            summary_msg = messages[summary_index]
            if summary_msg not in pinned:
                pinned.append(summary_msg)
            rest = [m for m in rest if m is not summary_msg]

        budget = max_messages - len(pinned)
        if budget <= 0:
            return pinned[:max_messages]

        if len(rest) <= budget:
            return pinned + rest

        tail_start = len(rest) - budget
        while tail_start > 0 and rest[tail_start].role == "tool":
            tail_start -= 1

        return pinned + rest[tail_start:]
