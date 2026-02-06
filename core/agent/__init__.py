"""Core agent/runtime package.

Keep this package import-light.

Public modules:
- `core.agent.message_engine`
- `core.agent.policy`
- `core.agent.policy_builder`
- `core.agent.modes.*`

Rationale:
- Avoid package-level export proxies (e.g. `__getattr__`) to keep imports explicit.
- `core.agent.modes` is imported widely (UI + prompt building). It must not pull
  in the runtime engine unless explicitly requested.
"""
