"""
ManageDocumentTool: CRUD for session-level persistent documents.

Documents (plan, memory, notes, etc.) survive context condensation and
are always injected into the system prompt, providing long-term memory
across turns.
"""
from typing import Dict, Any
from core.tools.base import BaseTool, ToolContext, ToolResult
from models.state import SessionDocument


class ManageDocumentTool(BaseTool):
    """Create, read, update, or delete session-level documents."""

    @property
    def name(self) -> str:
        return "manage_document"

    @property
    def description(self) -> str:
        return (
            "Manage session-level persistent documents that survive context condensation. "
            "Use this to maintain a 'plan', 'memory', 'notes', or any named document "
            "across the conversation. Documents are always visible in the system prompt.\n\n"
            "Actions:\n"
            "- create/update: Set or replace a document's content\n"
            "- read: Read a document's full content\n"
            "- delete: Remove a document\n"
            "- list: List all documents\n"
            "- append: Append text to an existing document"
        )

    @property
    def group(self) -> str:
        return "edit"

    @property
    def category(self) -> str:
        return "misc"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "read", "update", "delete", "list", "append"],
                    "description": "The action to perform"
                },
                "name": {
                    "type": "string",
                    "description": "Document name (e.g. 'plan', 'memory', 'notes'). Required for all actions except 'list'."
                },
                "content": {
                    "type": "string",
                    "description": "Document content. Required for create/update/append."
                },
            },
            "required": ["action"],
        }

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments.get("action", "")
        name = (arguments.get("name") or "").strip()
        content = arguments.get("content", "")

        conv = context.conversation
        if conv is None:
            return ToolResult("No conversation context available.", is_error=True)

        state = conv.get_state()
        seq = getattr(conv, "_seq_counter", 0)

        if action == "list":
            if not state.documents:
                return ToolResult("No documents in this session.")
            lines = []
            for doc_name, doc in state.documents.items():
                preview = (doc.content[:80] + "...") if len(doc.content) > 80 else doc.content
                lines.append(f"- **{doc_name}** ({len(doc.content)} chars): {preview}")
            return ToolResult("\n".join(lines))

        if not name:
            return ToolResult("'name' is required for this action.", is_error=True)

        if action in ("create", "update"):
            state.documents[name] = SessionDocument(
                name=name,
                content=content,
                updated_seq=seq,
            )
            conv.set_state(state)
            return ToolResult(f"Document '{name}' saved ({len(content)} chars).")

        elif action == "append":
            doc = state.documents.get(name)
            if doc is None:
                state.documents[name] = SessionDocument(
                    name=name,
                    content=content,
                    updated_seq=seq,
                )
            else:
                doc.content += "\n" + content
                doc.updated_seq = seq
            conv.set_state(state)
            total = len(state.documents[name].content)
            return ToolResult(f"Appended to '{name}' (total {total} chars).")

        elif action == "read":
            doc = state.documents.get(name)
            if doc is None:
                return ToolResult(f"Document '{name}' not found.", is_error=True)
            return ToolResult(doc.content)

        elif action == "delete":
            if name not in state.documents:
                return ToolResult(f"Document '{name}' not found.", is_error=True)
            del state.documents[name]
            conv.set_state(state)
            return ToolResult(f"Document '{name}' deleted.")

        return ToolResult(f"Unknown action: {action}", is_error=True)
