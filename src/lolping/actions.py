"""Sector -> injected function registry (used by DSH mode).

A slice only becomes selectable in DSH mode when it maps to an action here.
"""

from __future__ import annotations

CAPTURE_REGION = "capture_region"
OPEN_SEARCH = "open_search"

SEARCH_URL = "https://www.google.com/search?q={query}"


def sector_action(name: str) -> str | None:
    """Return the injected action for a slice name, or ``None``."""
    token = (name or "").strip().lower()
    if "missing" in token:
        return CAPTURE_REGION
    if "on my way" in token:
        return OPEN_SEARCH
    return None


def injected_indices(names) -> set[int]:
    return {index for index, name in enumerate(names) if sector_action(name) is not None}


def search_url(name: str) -> str:
    from urllib.parse import quote_plus

    return SEARCH_URL.format(query=quote_plus(f"{name} Hong Kong"))
