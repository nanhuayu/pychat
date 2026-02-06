from __future__ import annotations

from typing import Optional

from core.agent.policy import RunPolicy
from core.agent.modes.features import clamp_feature_flags, get_mode_feature_policy
from core.agent.modes.manager import ModeManager, resolve_mode_config


def build_run_policy(
    *,
    mode_slug: str,
    enable_thinking: Optional[bool] = None,
    enable_search: Optional[bool] = None,
    enable_mcp: Optional[bool] = None,
    mode_manager: Optional[ModeManager] = None,
) -> RunPolicy:
    """Build a RunPolicy from mode + feature toggles.

    Pure core helper (no Qt) so TUI/CLI can reuse it.

    Behavior:
    - Apply mode feature-policy clamping to tool flags.
    - Determine agent-like vs chat-like default policy.
    - Preserve the provided mode_slug in the returned policy.
    """

    slug = (mode_slug or "chat").strip() or "chat"

    # Resolve mode config (always falls back to chat).
    mode_cfg = resolve_mode_config(slug, mode_manager=mode_manager)

    # Runtime defaults (kept intentionally tiny).
    max_turns = 20
    context_window_limit = 100000
    auto_compress_enabled = None

    # Derive defaults from mode feature policy when caller passes None.
    try:
        fp = get_mode_feature_policy(mode_cfg)
        if enable_thinking is None:
            enable_thinking = bool(fp.default_thinking)
        if enable_mcp is None:
            enable_mcp = bool(fp.default_mcp)
        if enable_search is None:
            enable_search = bool(fp.default_search)
    except Exception:
        pass

    if enable_thinking is None:
        enable_thinking = True
    if enable_search is None:
        enable_search = False
    if enable_mcp is None:
        enable_mcp = False

    # Clamp flags according to mode policy.
    try:
        fp = get_mode_feature_policy(mode_cfg)
        enable_thinking, enable_mcp, enable_search = clamp_feature_flags(
            fp,
            enable_thinking=bool(enable_thinking),
            enable_mcp=bool(enable_mcp),
            enable_search=bool(enable_search),
        )
    except Exception:
        enable_thinking = bool(enable_thinking)
        enable_search = bool(enable_search)
        enable_mcp = bool(enable_mcp)

    # Build final policy.
    return RunPolicy(
        mode=str(slug),
        max_turns=int(max_turns),
        context_window_limit=int(context_window_limit),
        enable_thinking=bool(enable_thinking),
        enable_search=bool(enable_search),
        enable_mcp=bool(enable_mcp),
        tool_allowlist=None,
        auto_compress_enabled=auto_compress_enabled,
    )

