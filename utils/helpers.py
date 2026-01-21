"""
PyChat - Utility helpers
"""


def format_tokens(tokens: int) -> str:
    """Format token count with thousands separator"""
    return f"{tokens:,}"


def format_time_ms(ms: int) -> str:
    """Format milliseconds to readable time"""
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60000:
        return f"{ms / 1000:.2f}s"
    else:
        minutes = ms // 60000
        seconds = (ms % 60000) / 1000
        return f"{minutes}m {seconds:.1f}s"


def truncate_text(text: str, max_length: int = 50) -> str:
    """Truncate text with ellipsis"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."
