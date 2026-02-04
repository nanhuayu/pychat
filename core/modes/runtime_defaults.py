from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.modes.types import ModeConfig


@dataclass(frozen=True)
class ModeRuntimeDefaults:
    """Runtime defaults derived from a ModeConfig.

    Keep this free of core.agent imports to avoid circular dependencies.

    Notes:
    - auto_compress_enabled=None means: let the engine decide using (app_config + mode).
    """

    max_turns: int
    context_window_limit: int
    auto_compress_enabled: Optional[bool] = None


def get_mode_runtime_defaults(mode: ModeConfig) -> ModeRuntimeDefaults:
    """Derive a minimal, consistent set of runtime defaults.

    This is the single source of truth for mode-driven defaults that were
    previously duplicated across core.agent.* policy presets.
    """

    # Keep limits conservative and deterministic.
    context_window_limit = 100000
    max_turns = 20 if bool(mode.is_agent_like()) else 10

    # Defer compression decision to engine (app_config + agent-like gating).
    return ModeRuntimeDefaults(
        max_turns=int(max_turns),
        context_window_limit=int(context_window_limit),
        auto_compress_enabled=None,
    )
