"""Core agent/runtime package.

This package contains the unified runtime used by both Chat and Agent modes.
It must not depend on Qt.

Important: keep this module lightweight.
Many parts of the app import `core.agent.modes` for configuration; importing
that subpackage should not eagerly import the full runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .message_engine import MessageEngine, RunResult
    from .policy import RunPolicy
    from .policy_builder import build_run_policy


__all__ = [
    "MessageEngine",
    "RunResult",
    "RunPolicy",
    "build_run_policy",
]


def __getattr__(name: str) -> Any:
    if name in {"MessageEngine", "RunResult"}:
        from .message_engine import MessageEngine, RunResult

        return {"MessageEngine": MessageEngine, "RunResult": RunResult}[name]
    if name == "RunPolicy":
        from .policy import RunPolicy

        return RunPolicy
    if name == "build_run_policy":
        from .policy_builder import build_run_policy

        return build_run_policy
    raise AttributeError(name)
