"""Intent records for the DSH bridge.

Each committed slice with an injected action becomes one JSON line:

    {"ts": ..., "sector": 4, "name": "Enemy Missing", "action": "capture_region",
     "x": 812, "y": 430, "region": [x, y, w, h], "screenshot": "C:/...png"}

A DSH plugin can tail the file and act on the region; lolping itself never talks
to DSH directly, so either side can crash without taking the other down.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

from .config import app_data_dir

log = logging.getLogger(__name__)


def intents_path() -> Path:
    return app_data_dir() / "intents.jsonl"


def regions_dir() -> Path:
    path = app_data_dir() / "regions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_intent(record: dict[str, Any], path: Path | None = None) -> Path:
    """Append one intent record and return the file written."""
    target = Path(path) if path is not None else intents_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False) + "\n"
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(payload)
    return target


def make_record(
    *, sector: int, name: str, action: str, x: int, y: int,
    region: tuple[int, int, int, int] | None = None,
    screenshot: str = "",
    window_title: str = "",
    text: str = "",
    score: int = 0,
    mode: str = "",
) -> dict[str, Any]:
    return {
        "ts": dt.datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "sector": int(sector),
        "name": str(name),
        "action": str(action),
        "x": int(x),
        "y": int(y),
        "region": list(region) if region else None,
        "screenshot": screenshot,
        "window_title": window_title,
        "text": text,
        "score": int(score),
        "mode": mode,
    }


def capture_region(screen, rect: tuple[int, int, int, int], destination: Path) -> bool:
    """Grab a screen region to ``destination``; ``False`` when unavailable."""
    if screen is None:
        return False
    x, y, width, height = (int(value) for value in rect)
    try:
        pixmap = screen.grabWindow(0, x, y, width, height)
    except (RuntimeError, TypeError):  # pragma: no cover - platform edge case
        return False
    if pixmap.isNull():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(destination), "PNG"):
        return False
    return True
