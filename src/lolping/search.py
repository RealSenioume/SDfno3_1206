"""Search routing: text search vs image search, from a usability score."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

from .config import Config

#: Kept in sync with ``ocr.HIGH_CONFIDENCE`` / ``ocr.LOW_CONFIDENCE``.
HIGH_CONFIDENCE = 60
LOW_CONFIDENCE = 25

#: Default browser search engine (the user's default browser opens these).
TEXT_SEARCH_URL = "https://www.google.com/search?q={query}"
IMAGE_SEARCH_URL = "https://lens.google.com/"

#: Optional later: a per-user template in the settings dialog.
SEARCH_TEMPLATE = TEXT_SEARCH_URL


def text_search_url(query: str, template: str = SEARCH_TEMPLATE) -> str:
    return template.format(query=quote_plus(query.strip()))


def image_search_url() -> str:
    return IMAGE_SEARCH_URL


@dataclass
class SearchDecision:
    mode: str          # "text" | "both" | "image"
    query: str
    score: int
    reason: str


def decide(text: str, score: int) -> SearchDecision:
    """Route one ping to a search strategy.

    * high score -> a text search with the recognised line
    * middle     -> text search now, image search available as a fallback
    * low        -> image search only
    """
    query = (text or "").strip()
    if not query or score < LOW_CONFIDENCE:
        return SearchDecision("image", query, score, "no usable text")
    if score >= HIGH_CONFIDENCE:
        return SearchDecision("text", query, score, "confident text")
    return SearchDecision("both", query, score, "ambiguous text")


def urls_for(decision: SearchDecision) -> list[str]:
    """URLs to open for a decision (image search needs a clipboard image)."""
    if decision.mode == "text":
        return [text_search_url(decision.query)]
    if decision.mode == "both":
        return [text_search_url(decision.query)]
    return [image_search_url()]
