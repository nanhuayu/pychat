from __future__ import annotations

from typing import Optional, Protocol

from core.agent.policy import RunPolicy
from core.agent.modes.runtime_defaults import get_mode_runtime_defaults
from core.agent.modes.policy import clamp_feature_flags, get_mode_feature_policy
from core.agent.modes.manager import ModeManager


class _ModeConfigProto(Protocol):
    def is_agent_like(self) -> bool: ...


class _ModeManagerProto(Protocol):
    def get(self, slug: str) -> _ModeConfigProto: ...


def build_run_policy(
    *,
    mode_slug: str,
    enable_thinking: Optional[bool] = None,
    enable_search: Optional[bool] = None,
    enable_mcp: Optional[bool] = None,
    mode_manager: Optional[_ModeManagerProto] = None,
) -> RunPolicy:
    """Build a RunPolicy from mode + feature toggles.

    Pure core helper (no Qt) so TUI/CLI can reuse it.

    Behavior:
    - Apply mode feature-policy clamping to tool flags.
    - Determine agent-like vs chat-like default policy.
    - Preserve the provided mode_slug in the returned policy.
    """

    slug = (mode_slug or "chat").strip() or "chat"

    # Resolve mode config for defaults + feature policy.
    resolved_manager = mode_manager
    if resolved_manager is None:
        try:
            resolved_manager = ModeManager()
        except Exception:
            resolved_manager = None

    mode_cfg = None
    if resolved_manager is not None:
        try:
            mode_cfg = resolved_manager.get(slug)
        except Exception:
            mode_cfg = None

    is_agent_like = False
    try:
        if mode_cfg is not None:
            is_agent_like = bool(mode_cfg.is_agent_like())
    except Exception:
        is_agent_like = False
    if not is_agent_like:
        is_agent_like = (slug.lower() == "agent")

    # Runtime defaults are mode-driven (single source of truth).
    try:
        if mode_cfg is not None:
            defaults = get_mode_runtime_defaults(mode_cfg)
        else:
            defaults = None
    except Exception:
        defaults = None

    if defaults is None:
        max_turns = 20 if bool(is_agent_like) else 10
        context_window_limit = 100000
        auto_compress_enabled = None
    else:
        max_turns = int(getattr(defaults, "max_turns", 10) or 10)
        context_window_limit = int(getattr(defaults, "context_window_limit", 100000) or 100000)
        auto_compress_enabled = getattr(defaults, "auto_compress_enabled", None)

    # Derive defaults from mode feature policy when caller passes None.
    try:
        if mode_cfg is not None:
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
        if mode_cfg is not None:
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

