"""Content moderation — keyword filters, spam detection."""
from __future__ import annotations
import re

BLOCKED_PATTERNS = [
    re.compile(r"(?i)(buy\s+now|click\s+here\s+to\s+win|congratulations\s+you\s+won)"),
]

def check_content(text: str) -> tuple[bool, list[str]]:
    """Returns (is_clean, reasons_if_flagged)."""
    flags = []
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(text):
            flags.append(f"matched_pattern:{pattern.pattern[:40]}")
    return len(flags) == 0, flags
