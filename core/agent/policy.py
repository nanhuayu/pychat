from __future__ import annotations

from core.config.schema import AppConfig
from core.state.services.compression_service import CompressionPolicy


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
