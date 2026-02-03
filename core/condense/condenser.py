from typing import List, Optional

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

    def _find_last_summary_index(self, messages: List[Message]) -> int:
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].metadata.get("is_summary"):
                return i
        return -1

    def _find_last_user_index(self, messages: List[Message], before_index: int) -> int:
        for i in range(min(before_index, len(messages) - 1), -1, -1):
            m = messages[i]
            if m.role == "user" and not m.metadata.get("is_summary"):
                return i
        return -1

    def _build_transcript(self, messages: List[Message]) -> str:
        lines: List[str] = []
        for m in messages:
            if m.role == "system":
                continue

            role = m.role.upper()
            content = m.summary if m.summary else m.content
            if content is None:
                content = ""

            block = f"{role}:\n{content}".strip()

            if m.role == "assistant" and m.tool_calls:
                tool_lines: List[str] = []
                for tc in m.tool_calls:
                    fn = (tc.get("function") or {}).get("name")
                    args = (tc.get("function") or {}).get("arguments")
                    result = tc.get("result")
                    tool_lines.append(
                        f"- tool_call id={tc.get('id')} name={fn} args={args} result={result}"
                    )
                if tool_lines:
                    block = f"{block}\n\nTOOL_CALLS:\n" + "\n".join(tool_lines)

            lines.append(block)

        return "\n\n---\n\n".join(lines).strip()

    def _count_active(self, messages: List[Message], start: int, end: int) -> int:
        count = 0
        for i in range(max(0, start), min(len(messages), end)):
            m = messages[i]
            if m.role == "system":
                continue
            if m.condense_parent or m.truncation_parent:
                continue
            count += 1
        return count

    def _find_last_active_index(self, messages: List[Message]) -> int:
        for i in range(len(messages) - 1, -1, -1):
            m = messages[i]
            if m.role == "system":
                continue
            if m.condense_parent or m.truncation_parent:
                continue
            return i
        return -1

    async def condense_message(self, 
                               message: Message, 
                               provider: Provider) -> bool:
        """
        Generates a concise summary for a single message and stores it in message.summary.
        This is useful for Agent Mode where output can be very large.
        """
        if not message.content or len(message.content) < 200:
            return False
            
        # Check if already summarized
        if message.summary:
            return False

        print(f"[Condenser] Summarizing message {message.id[:8]}...")
        
        prompt = f"""Please provide a concise summary of the following message content.
Focus on the key actions taken, results obtained, or decisions made.
Keep it under 10000 words.

Content:
{message.content}
"""
        
        summary_conv = Conversation(
            id="temp_msg_summary",
            messages=[Message(role="user", content=prompt)],
            model=None,
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
    async def summarize_last_session(self, conversation: Conversation, provider: Provider) -> bool:
        messages = conversation.messages
        if not messages:
            return False

        end_index = -1
        for i in range(len(messages) - 1, -1, -1):
            m = messages[i]
            if m.role == "assistant" and not m.tool_calls:
                end_index = i
                break

        if end_index < 0:
            return False

        end_msg = messages[end_index]
        if end_msg.summary:
            return False

        start_index = self._find_last_user_index(messages, end_index - 1)
        if start_index < 0:
            return False

        session_messages = messages[start_index : end_index + 1]
        has_tools = any(m.role == "assistant" and m.tool_calls for m in session_messages) or any(
            m.role == "tool" for m in session_messages
        )
        total_chars = sum(len((m.content or "")) for m in session_messages)
        if not has_tools and total_chars < 1200:
            return False

        transcript = self._build_transcript(session_messages)
        if not transcript:
            return False

        prompt = f"""请为下面这段完整会话生成一份可用于后续上下文的精炼总结。
要求：
1) 只总结事实与结论，不要虚构；
2) 包含：目标/需求、关键操作与结果、涉及的文件或命令（如有）、当前状态与未完成事项（如有）；
3) 尽量短（建议 200-400 中文字），但要信息密度高。

会话内容：
{transcript}
"""

        summary_conv = Conversation(
            id="temp_session_summary",
            messages=[Message(role="user", content=prompt)],
            model=None,
            mode="chat",
        )

        try:
            response_msg = await self.client.send_message(
                provider,
                summary_conv,
                enable_thinking=False,
                enable_search=False,
                enable_mcp=False,
            )
            end_msg.summary = response_msg.content
            end_msg.metadata["has_session_summary"] = True
            return True
        except Exception as e:
            print(f"[Condenser] Failed to summarize session: {e}")
            return False

    async def condense(
        self,
        conversation: Conversation,
        provider: Provider,
        keep_last_n: int = 5,
    ) -> bool:
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
        if not messages:
            return False

        last_summary_index = self._find_last_summary_index(messages)

        start_index = last_summary_index + 1
        if start_index <= 0:
            start_index = 1

        active_count = 0
        keep_start = len(messages)
        for i in range(len(messages) - 1, start_index - 1, -1):
            m = messages[i]
            if m.role == "system":
                continue
            if m.condense_parent or m.truncation_parent:
                continue
            active_count += 1
            if active_count >= keep_last_n:
                keep_start = i
                break

        if keep_start >= len(messages):
            return False

        while keep_start > start_index and messages[keep_start].role == "tool":
            keep_start -= 1

        last_active_index = self._find_last_active_index(messages)
        if last_active_index >= 0:
            last_active = messages[last_active_index]
            if last_active.role == "assistant" and not last_active.tool_calls:
                last_session_start = self._find_last_user_index(messages, last_active_index - 1)
                if last_session_start >= start_index:
                    if self._count_active(messages, last_session_start, len(messages)) <= keep_last_n:
                        keep_start = last_session_start
                        while True:
                            prev_session_start = self._find_last_user_index(messages, keep_start - 1)
                            if prev_session_start < start_index:
                                break
                            if self._count_active(messages, prev_session_start, len(messages)) <= keep_last_n:
                                keep_start = prev_session_start
                                continue
                            break

        end_index = keep_start
        
        if start_index >= end_index:
            return False # Nothing to summarize
            
        messages_to_summarize = messages[start_index:end_index]
        if not messages_to_summarize:
            return False

        print(f"[Condenser] Summarizing {len(messages_to_summarize)} messages (Indices {start_index} to {end_index})...")

        previous_summary = ""
        if last_summary_index >= 0:
            previous_summary = messages[last_summary_index].content or ""

        transcript = self._build_transcript(messages_to_summarize)
        prompt = f"""{SUMMARY_PROMPT}

## Previous Summary (if any)
{previous_summary}

## New Conversation Delta
{transcript}
"""

        summary_conv = Conversation(
            id="temp_summary",
            messages=[Message(role="user", content=prompt)],
            model=conversation.model,
            mode="chat",
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
