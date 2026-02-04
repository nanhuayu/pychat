"""Controller layer.

Controllers/Managers orchestrate application flows between UI widgets and services.
UI widgets should stay focused on presentation and user interaction.
"""

from .prompt_optimizer import PromptOptimizer

__all__ = ["PromptOptimizer"]
