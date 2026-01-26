"""Pure image encoding utilities (no Qt/UI dependencies).

This module provides base64 encoding for image files, used by both
services/llm layer (for API requests) and UI layer (for display).

Separate from ui/utils/image_utils.py to avoid circular imports.
"""

from __future__ import annotations

import base64
import mimetypes
from typing import Optional


def encode_image_file_to_data_url(file_path: str) -> Optional[str]:
    """Encode an image file path into a base64 data URL."""
    if not isinstance(file_path, str) or not file_path:
        return None

    try:
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "image/png"

        with open(file_path, "rb") as f:
            raw = f.read()

        b64 = base64.b64encode(raw).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"
    except Exception:
        return None
