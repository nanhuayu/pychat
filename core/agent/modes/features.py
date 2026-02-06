from __future__ import annotations

from dataclasses import dataclass

from core.agent.modes.types import ModeConfig


def _group_names(mode: ModeConfig) -> set[str]:
    names: set[str] = set()
    for g in mode.groups or []:
        if isinstance(g, tuple) and g:
            names.add(str(g[0]))
        else:
            names.add(str(g))
    return names


@dataclass(frozen=True)
class ModeFeaturePolicy:
    """Mode-driven feature defaults and constraints.

    This is used by:
    - UI: enable/disable toggles + compute defaults
    - policy_builder: derive RunPolicy feature flags
    """

    allow_thinking: bool = True
    allow_mcp: bool = False
    allow_search: bool = False

    default_thinking: bool = False
    default_mcp: bool = False
    default_search: bool = False


def get_mode_feature_policy(mode: ModeConfig) -> ModeFeaturePolicy:
    """Derive UI + runtime feature policy from ModeConfig.groups.

    Conventions:
    - group 'mcp' => tools (system + MCP) are allowed and default-on.
    - group 'search' => web search is allowed and default-on.
    - agent-like modes default thinking on.
    """

    groups = _group_names(mode)

    # Allow all capabilities in all modes, but use groups to determine defaults.
    allow_mcp = True
    allow_search = True

    default_mcp = bool("mcp" in groups or mode.is_agent_like())
    default_search = bool("search" in groups)
    default_thinking = bool(mode.is_agent_like())

    return ModeFeaturePolicy(
        allow_thinking=True,
        allow_mcp=allow_mcp,
        allow_search=allow_search,
        default_thinking=default_thinking,
        default_mcp=default_mcp,
        default_search=default_search,
    )


def clamp_feature_flags(
    policy: ModeFeaturePolicy,
    *,
    enable_thinking: bool,
    enable_mcp: bool,
    enable_search: bool,
) -> tuple[bool, bool, bool]:
    """Clamp user/UI flags by policy (disallowed -> forced False)."""

    out_thinking = bool(enable_thinking) if policy.allow_thinking else False
    out_mcp = bool(enable_mcp) if policy.allow_mcp else False
    out_search = bool(enable_search) if policy.allow_search else False
    return out_thinking, out_mcp, out_search
