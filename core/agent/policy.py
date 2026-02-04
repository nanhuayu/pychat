from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Set

from core.config.schema import AppConfig
from core.state.services.compression_service import CompressionPolicy


@dataclass(frozen=True)
class RunPolicy:
    """Extremely small policy object.

    The goal is to make chat/agent differences purely parameter-driven.
    """

    # Mode slug (should match `core.modes.types.ModeConfig.slug`).
    mode: str = "chat"
    max_turns: int = 10
    context_window_limit: int = 100000
    enable_thinking: bool = True
    enable_search: bool = False
    enable_mcp: bool = False

    # If provided, tools must be in this allowlist (in addition to enable_search/enable_mcp toggles).
    tool_allowlist: Optional[Set[str]] = None

    # None means "defer to app_config".
    auto_compress_enabled: Optional[bool] = None


def chat_policy(
    *,
    enable_thinking: bool = True,
    enable_search: bool = False,
    enable_mcp: bool = False,
    max_turns: int = 10,
    context_window_limit: int = 100000,
    tool_allowlist: Optional[Set[str]] = None,
) -> RunPolicy:
    return RunPolicy(
        mode="chat",
        max_turns=int(max_turns),
        context_window_limit=int(context_window_limit),
        enable_thinking=bool(enable_thinking),
        enable_search=bool(enable_search),
        enable_mcp=bool(enable_mcp),
        tool_allowlist=set(tool_allowlist) if tool_allowlist else None,
    )


def agent_policy(
    *,
    enable_thinking: bool = True,
    enable_search: bool = True,
    enable_mcp: bool = True,
    max_turns: int = 20,
    context_window_limit: int = 100000,
    tool_allowlist: Optional[Set[str]] = None,
) -> RunPolicy:
    # Agent defaults to auto compress unless app_config disables it.
    return RunPolicy(
        mode="agent",
        max_turns=int(max_turns),
        context_window_limit=int(context_window_limit),
        enable_thinking=bool(enable_thinking),
        enable_search=bool(enable_search),
        enable_mcp=bool(enable_mcp),
        tool_allowlist=set(tool_allowlist) if tool_allowlist else None,
        auto_compress_enabled=True,
    )


def build_compression_policy(app_config: AppConfig) -> CompressionPolicy:
    ctx = getattr(app_config, "context", None)
    pol = getattr(ctx, "compression_policy", None)

    def _int(v, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return default

    def _float(v, default: float) -> float:
        try:
            return float(v)
        except Exception:
            return default

    per_message_lookback = _int(getattr(pol, "per_message_lookback", 20), 20)
    tool_min_chars = _int(getattr(pol, "tool_min_chars", 200), 200)
    assistant_min_chars = _int(getattr(pol, "assistant_min_chars", 800), 800)
    max_active_messages = _int(getattr(pol, "max_active_messages", 20), 20)
    token_threshold_ratio = _float(getattr(pol, "token_threshold_ratio", 0.7), 0.7)
    keep_last_n = _int(getattr(pol, "keep_last_n", 10), 10)

    return CompressionPolicy(
        per_message_lookback=per_message_lookback,
        tool_min_chars=tool_min_chars,
        assistant_min_chars=assistant_min_chars,
        max_active_messages=max_active_messages,
        token_threshold_ratio=token_threshold_ratio,
        keep_last_n=keep_last_n,
    )
