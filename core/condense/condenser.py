import uuid
from typing import List, Any

from models.conversation import Conversation, Message
from models.provider import Provider
from models.state import SessionState
from core.condense.prompts import SUMMARY_PROMPT, SUMMARY_SYSTEM_PROMPT
class ContextCondenser:
    """
    Handles conversation condensation (summarization) to manage context window.
    Uses 'Fresh Start' model with non-destructive history (messages are tagged, not deleted).
    """

    def __init__(self, client: Any):
        self.client = client

    def _build_transcript(self, messages: List[Message], *, include_tool_details: bool = False) -> str:
        """Build a compact transcript for summarization.

        Notes:
        - Skips tool-role messages (often verbose and duplicated).
        - Uses per-message summaries when available.
        - Includes a minimal TOOL_CALLS section on assistant messages.
        """
        def _compact(s: str, limit: int = 240) -> str:
            s = (s or "").replace("\r", " ").replace("\n", " ").strip()
            while "  " in s:
                s = s.replace("  ", " ")
            return (s[:limit] + "...") if len(s) > limit else s

        lines: List[str] = []
        for m in messages:
            if m.role in ("system", "tool"):
                continue

            role = (m.role or "").upper()
            content = m.summary if m.summary else m.content
            if content is None:
                content = ""

            block = f"{role}:\n{content}".strip()

            if m.role == "assistant" and m.tool_calls:
                tool_lines: List[str] = []
                for tc in m.tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    fn = (tc.get("function") or {}).get("name")
                    args = (tc.get("function") or {}).get("arguments")
                    result = tc.get("result")

                    if include_tool_details:
                        tool_lines.append(
                            f"- tool_call id={tc.get('id')} name={fn} args={_compact(str(args or ''))} result={_compact(str(result or ''))}"
                        )
                    else:
                        rs = _compact(str(result or ""))
                        if rs:
                            tool_lines.append(f"- tool_call name={fn} result={rs}")
                        else:
                            tool_lines.append(f"- tool_call name={fn}")

                if tool_lines:
                    block = f"{block}\n\nTOOL_CALLS:\n" + "\n".join(tool_lines)

            lines.append(block)

        return "\n\n---\n\n".join(lines).strip()

    async def condense_message(self, message: Message, provider: Provider) -> bool:
        """为单条消息生成摘要并写入 message.summary（不插入 summary-message）。"""
        if not message.content:
            return False

        # 已有摘要就不重复压缩
        if message.summary:
            return False

        # 只压缩长消息，避免压缩短消息浪费token
        if len(message.content) < 500:
            return False

        prompt = f"""请为以下消息生成一个简洁的摘要，保留关键信息和重要细节。

原始消息：
{message.content}

要求：
1. 摘要长度控制在原文的20%以内
2. 保留关键事实、数据、结论
3. 使用清晰的要点形式
4. 如果有代码或技术细节，请保留重要部分
"""

        summary_conv = Conversation(
            title="Message Condensation",
            messages=[Message(role="user", content=prompt)],
            settings={"stream": False, "system_prompt_override": "You are a concise summarizer. Summarize the given message. Do not call tools. Output text only."},
        )
        try:
            summary_msg = await self.client.send_message(
                provider,
                summary_conv,
                enable_thinking=False,
                enable_search=False,
                enable_mcp=False,
            )
            message.summary = summary_msg.content
            print(f"[Condenser] 已为消息生成摘要 (seq_id={message.seq_id})")
            return True
        except Exception as e:
            print(f"[Condenser] 生成消息摘要失败: {e}")
            return False

    async def condense_state(
        self,
        conversation: Conversation,
        provider: Provider,
        state: SessionState,
        keep_last_n: int = 5
    ) -> bool:
        """
        Condenses conversation and updates SessionState.summary directly.
        Archives old summary to state.archived_summaries.
        """
        messages = conversation.messages
        if not messages:
            return False
            
        # Identify messages to summarize
        # We want to keep 'keep_last_n' active non-system messages
        # summarizing everything before that which hasn't been condensed yet.
        
        active_indices = []
        for i, m in enumerate(messages):
            if m.role == "system": continue
            if m.condense_parent: continue
            active_indices.append(i)
            
        if len(active_indices) <= keep_last_n:
            return False
            
        # Indices to keep
        indices_to_keep = set(active_indices[-keep_last_n:])
        
        # Messages to summarize: Active messages NOT in indices_to_keep
        indices_to_summarize = [i for i in active_indices if i not in indices_to_keep]
        
        if not indices_to_summarize:
            return False
            
        start_idx = indices_to_summarize[0]
        end_idx = indices_to_summarize[-1] + 1
        
        # Verify contiguity (should be contiguous if list is ordered)
        messages_to_summarize = messages[start_idx:end_idx]
        
        print(f"[Condenser] State Condense: Summarizing {len(messages_to_summarize)} messages...")

        include_tool_details = bool((conversation.settings or {}).get('summary_include_tool_details', False))
        transcript = self._build_transcript(messages_to_summarize, include_tool_details=include_tool_details)

        prompt = f"""## Previous Summary
{state.summary}

## New Conversation Delta
{transcript}
"""
        summary_model = ((conversation.settings or {}).get('summary_model') or conversation.model or provider.default_model)
        summary_system_prompt = ((conversation.settings or {}).get('summary_system_prompt') or SUMMARY_SYSTEM_PROMPT)

        summary_conv = Conversation(
            id='temp_state_condense',
            messages=[Message(role='user', content=prompt)],
            model=summary_model,
            mode='chat',
            settings={
                'stream': False,
                'system_prompt_override': str(summary_system_prompt or '').strip(),
            },
        )
        try:
            response_msg = await self.client.send_message(
                provider,
                summary_conv,
                enable_thinking=False,
                enable_search=False,
                enable_mcp=False
            )
            
            new_summary = response_msg.content or "No summary generated."
            
            # Archive old
            if state.summary:
                state.archived_summaries.append(state.summary)
                
            # Update state
            state.summary = new_summary
            
            # Tag messages
            condense_id = str(uuid.uuid4())
            for msg in messages_to_summarize:
                msg.condense_parent = condense_id
                
            print(f"[Condenser] State updated. Archived {len(state.archived_summaries)} summaries.")
            return True
            
        except Exception as e:
            print(f"[Condenser] Failed to condense state: {e}")
            return False
