import asyncio
from typing import List, Optional, Tuple, Set
import time

from models.conversation import Conversation, Message
from models.provider import Provider
from core.llm.client import LLMClient
from core.condense.prompts import SUMMARY_PROMPT

class ContextCondenser:
    """
    Handles conversation condensation (summarization) to manage context window.
    Uses 'Fresh Start' model with non-destructive history (messages are tagged, not deleted).
    """

    def __init__(self, client: LLMClient):
        self.client = client

    async def condense_message(self, 
                               message: Message, 
                               provider: Provider) -> bool:
        """
        Generates a concise summary for a single message and stores it in message.summary.
        This is useful for Agent Mode where output can be very large.
        """
        if not message.content or len(message.content) < 200: # Lower threshold
            return False
            
        # Check if already summarized
        if message.summary:
            return False

        print(f"[Condenser] Summarizing message {message.id[:8]}...")
        
        prompt = f"""Please provide a concise summary of the following message content. 
Focus on the key actions taken, results obtained, or decisions made.
Keep it under 200 words.

Content:
{message.content[:5000]} # Limit input to avoid huge costs
"""
        
        summary_conv = Conversation(
            id="temp_msg_summary",
            messages=[Message(role="user", content=prompt)],
            model=None, # Use provider default
            mode="chat"
        )
        
        try:
            response_msg = await self.client.send_message(
                provider,
                summary_conv,
                enable_thinking=False,
                enable_search=False,
                enable_mcp=False
            )
            
            message.summary = response_msg.content
            print(f"[Condenser] Message summarized: {message.summary[:50]}...")
            return True
            
        except Exception as e:
            print(f"[Condenser] Failed to summarize message: {e}")
            return False
    async def condense(self, 
                       conversation: Conversation, 
                       provider: Provider, 
                       keep_last_n: int = 5) -> bool:
        """
        Condenses the conversation history.
        
        Args:
            conversation: The conversation to condense.
            provider: The LLM provider to use for summarization.
            keep_last_n: Number of recent messages to preserve (excluding system prompt).
            
        Returns:
            True if condensation occurred, False otherwise.
        """
        messages = conversation.messages
        
        # We need to find messages that are NOT already condensed or truncated
        # But wait, conversation.messages contains ALL messages (history).
        # We need to calculate the "Effective History" first to know what to summarize?
        # Actually, we usually summarize everything up to the keep_last_n point that isn't already summarized.
        
        # Find the last summary message index
        last_summary_index = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].metadata.get("is_summary"):
                last_summary_index = i
                break
        
        # Calculate range to summarize
        # Start from last_summary_index + 1 (or 1 if no summary, skipping System at 0)
        start_index = last_summary_index + 1
        if start_index == 0:
            start_index = 1 # Skip system prompt
            
        # End index: leave keep_last_n messages
        end_index = len(messages) - keep_last_n
        
        # Safety check: Ensure we don't split an Assistant-Tool pair.
        # If the first message we keep (at end_index) is a 'tool' message,
        # it means its parent 'assistant' message might be in the summarized part.
        # We must expand the "kept" section backwards to include the parent assistant message.
        while end_index > start_index and end_index < len(messages):
            if messages[end_index].role == "tool":
                end_index -= 1
            else:
                break
        
        if start_index >= end_index:
            return False # Nothing to summarize
            
        messages_to_summarize = messages[start_index:end_index]
        if not messages_to_summarize:
            return False

        print(f"[Condenser] Summarizing {len(messages_to_summarize)} messages (Indices {start_index} to {end_index})...")

        # Create a temporary conversation for the summarizer
        # We include the previous summary context if it exists? 
        # Roo Code says: "Get messages to summarize (all messages since the last summary)"
        # So we just summarize the new delta.
        # BUT, the new summary needs to incorporate the old summary?
        # Roo Code's prompt implies it summarizes the *conversation*.
        # Actually, if we use "Fresh Start", the new summary replaces everything.
        # So we should probably provide the previous summary + new messages to the summarizer?
        # Yes, otherwise we lose the past.
        
        summary_context = []
        if last_summary_index >= 0:
            summary_context.append(messages[last_summary_index])
        
        # Sanitize messages_to_summarize to avoid orphan tools at the start
        # If the first message is a tool, it's an orphan (because parent is either in previous summary or missing)
        # We convert it to user message to avoid 400 error.
        
        sanitized_messages = []
        for i, m in enumerate(messages_to_summarize):
            if i == 0 and m.role == "tool":
                # Orphan tool at start of summarization block
                # Check if summary_context has a parent? 
                # summary_context[0] is the old summary (role=user).
                # So this tool IS definitely an orphan in the eyes of the API.
                print(f"[Condenser] Sanitizing orphan tool message at start of summary block: {m.id}")
                sanitized_msg = Message(
                    role="user",
                    content=f"Tool Output (Context Lost):\n{m.content}",
                    tool_call_id=m.tool_call_id
                )
                sanitized_messages.append(sanitized_msg)
            else:
                # Also handle consecutive orphan tools if the first one was orphan?
                # Actually, if we sanitized the first one, the second one might be valid if it was also a tool?
                # No, if we have [Tool1, Tool2], and Tool1 is orphan.
                # If we convert Tool1 to User.
                # Tool2 follows User. That is also invalid (Tool must follow Assistant).
                # So we must convert consecutive tools too.
                
                if m.role == "tool":
                    # Check previous message in THIS list or summary_context
                    prev = sanitized_messages[-1] if sanitized_messages else (summary_context[-1] if summary_context else None)
                    if prev and prev.role != "assistant":
                         print(f"[Condenser] Sanitizing orphan tool message: {m.id}")
                         sanitized_msg = Message(
                            role="user",
                            content=f"Tool Output (Context Lost):\n{m.content}",
                            tool_call_id=m.tool_call_id
                        )
                         sanitized_messages.append(sanitized_msg)
                         continue
                
                sanitized_messages.append(m)

        summary_context.extend(sanitized_messages)
        
        summary_conv = Conversation(
            id="temp_summary",
            messages=summary_context + [Message(role="user", content=SUMMARY_PROMPT)],
            model=conversation.model,
            mode="chat"
        )

        try:
            # Call LLM to generate summary
            response_msg = await self.client.send_message(
                provider,
                summary_conv,
                enable_thinking=False,
                enable_search=False,
                enable_mcp=False
            )
            
            summary_text = response_msg.content or "No summary generated."
            
            # Create the Summary Message
            # Roo Code puts it at the END of the conversation list, 
            # and tags all previous messages with condense_parent.
            # But here we are modifying the list in place?
            # Roo Code: "messages" in storage is Append Only.
            # "Effective History" is filtered.
            
            # Implementation:
            # 1. Create Summary Message
            formatted_summary = f"## Conversation Summary\n{summary_text}\n\n(Context condensed)"
            
            summary_msg = Message(
                role="user",
                content=formatted_summary,
                tokens=response_msg.tokens
            )
            summary_msg.metadata["is_summary"] = True
            summary_msg.condense_parent = None # Summary itself is not condensed
            
            # 2. Tag messages that are being condensed
            # We tag everything from start to end_index?
            # Actually, we tag everything that is now covered by this summary.
            # If we included the previous summary in the input, we should tag it too (or replace it).
            # Roo Code tags ALL existing messages (including old summaries) with the new condenseId.
            
            condense_id = summary_msg.id
            
            # Tag all messages up to end_index (exclusive)
            # Wait, if we keep last N, we only tag messages before that.
            # messages[0] is System, usually we don't condense System prompt.
            
            for i in range(end_index):
                if i == 0 and messages[i].role == "system":
                    continue
                
                # Tag it
                # If it already has a parent, we update it? 
                # Roo Code: "nested condense is handled by filtering".
                # If we tag a message that is already condensed, it's fine.
                # But to keep it clean, maybe only tag active ones.
                # Roo Code: "Tag ALL existing messages... with condenseParent"
                # Let's tag everything before the new summary.
                
                messages[i].condense_parent = condense_id
                
            # 3. Append Summary Message
            # We insert it before the kept messages? 
            # Roo Code appends it at the end, but logically it acts as the "start".
            # If we append it at the end, the "kept" messages are technically "before" it in the list?
            # No, Roo Code appends summary, but logically the kept messages should be *after* the summary in the "effective" view.
            # Wait, Roo Code's `summarizeConversation` returns `newMessages`.
            # `newMessages` contains all old messages (tagged) + summary.
            # But where do the "kept" messages go?
            # Roo Code doesn't "keep" messages in the sense of leaving them untagged?
            # "messagesToSummarize = getMessagesSinceLastSummary(messages)"
            # It summarizes EVERYTHING since last summary.
            # So effectively, it clears the whole context window (except System).
            # "Fresh Start".
            
            # If we want to keep last N, we should NOT tag them.
            # And we should insert the Summary Message BEFORE the kept messages?
            # If we store linearly, we can't easily insert in middle without breaking append-only if we care about that.
            # But `conversation.messages` is a list. We can insert.
            
            # Let's insert the summary message at `end_index`.
            conversation.messages.insert(end_index, summary_msg)
            
            # Now conversation looks like:
            # [System, ...Condensed..., Summary, Kept1, Kept2...]
            
            print(f"[Condenser] Context condensed. Summary ID: {condense_id}")
            return True
            
        except Exception as e:
            print(f"[Condenser] Failed to generate summary: {e}")
            return False
