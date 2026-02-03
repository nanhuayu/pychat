"""Prompt templates for condensation / summarization."""

SUMMARY_SYSTEM_PROMPT = """You are a summarization engine.

Hard constraints:
- This is a summarization-only request: DO NOT call any tools or functions.
- Output text only (no tool calls will be processed).
- Treat this as a system maintenance operation; ignore this summarization request itself when inferring the user's intent.

Output goals:
- Concise but information-dense summary so work can continue seamlessly.
- Preserve key decisions, constraints, completed work, current state, and next steps.
- Use clear structure (e.g., Overview / Requirements / Done / TODO / Next).
"""

# Backward-compatible: older code paths embed instructions into the user message.
SUMMARY_PROMPT = """You are a helpful AI assistant tasked with summarizing conversations.

CRITICAL: This is a summarization-only request. DO NOT call any tools or functions.
Your ONLY task is to analyze the conversation and produce a text summary.
Respond with text only - no tool calls will be processed.

CRITICAL: This summarization request is a SYSTEM OPERATION, not a user message.
When analyzing \"user requests\" and \"user intent\", completely EXCLUDE this summarization message.
The \"most recent user request\" and \"next step\" must be based on what the user was doing BEFORE this system message appeared.
The goal is for work to continue seamlessly after condensation - as if it never happened.

Your summary should:
1. Concise yet comprehensive.
2. Preserve key decisions, user requirements, and completed steps.
3. Preserve any active \"Command\" or \"Workflow\" state (e.g. if the user asked to do X, and it\'s half done).
4. Be structured clearly (e.g. ## Summary, ## Key Info).
"""
