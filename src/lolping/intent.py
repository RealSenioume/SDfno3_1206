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

from PyQt5.QtCore import Qt

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


def capture_centered(
    screen, point, width: int, height: int, destination: Path
) -> bool:
    """Grab a ``width x height`` crop centred on ``point``, padding at edges.

    The plain clamp used to move the wheel centre towards the middle of the
    captured image whenever the wheel sat near a screen edge, so OCR read the
    wrong part of the screen. This keeps the wheel centre at the image centre
    and fills the off-screen margin with opaque black instead.
    """
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QImage, QPainter

    if screen is None:
        return False
    area = screen.geometry()
    try:
        dpr = max(1.0, float(screen.devicePixelRatio() or 1.0))
        shot = screen.grabWindow(0)
    except (RuntimeError, TypeError):  # pragma: no cover - platform edge case
        return False
    if shot.isNull():
        return False
    source = shot.toImage()
    canvas_w = max(1, int(round(width * dpr)))
    canvas_h = max(1, int(round(height * dpr)))
    canvas = QImage(canvas_w, canvas_h, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.black)
    desired_x = point.x() - width / 2.0
    desired_y = point.y() - height / 2.0
    sx = (desired_x - area.x()) * dpr
    sy = (desired_y - area.y()) * dpr
    src_x0 = max(0.0, sx)
    src_y0 = max(0.0, sy)
    src_x1 = min(float(source.width()), sx + canvas_w)
    src_y1 = min(float(source.height()), sy + canvas_h)
    if src_x1 > src_x0 and src_y1 > src_y0:
        painter = QPainter(canvas)
        try:
            painter.drawImage(
                QRectF(src_x0 - sx, src_y0 - sy, src_x1 - src_x0, src_y1 - src_y0),
                source,
                QRectF(src_x0, src_y0, src_x1 - src_x0, src_y1 - src_y0),
            )
        finally:
            painter.end()
    destination.parent.mkdir(parents=True, exist_ok=True)
    return bool(canvas.save(str(destination), "PNG"))


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
