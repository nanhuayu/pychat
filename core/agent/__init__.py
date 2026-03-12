"""Legacy agent package — DEPRECATED.

All public APIs have moved:
- ``core.agent.policy.RunPolicy``        → ``core.task.types.RunPolicy``
- ``core.agent.policy_builder``          → ``core.task.builder``
- ``core.agent.message_engine``          → ``core.task.task.Task``
- ``core.agent.modes.*``                 → ``core.modes.*``

This package is kept ONLY for backward compatibility during the
migration period. New code should import from the new locations.
"""
