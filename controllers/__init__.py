"""Controller layer.

Controllers/Managers orchestrate application flows between UI widgets and services.
UI widgets should stay focused on presentation and user interaction.
"""

from .stream_manager import StreamManager

__all__ = ["StreamManager"]
