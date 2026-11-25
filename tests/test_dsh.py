"""Tests for DSH mode, injected actions and the intent record."""

from __future__ import annotations

import json
import os
import sys
import shutil
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt5.QtCore import QPoint  # noqa: E402
from PyQt5.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import lolping.overlay as overlay_module  # noqa: E402
from lolping import actions, intent  # noqa: E402
from lolping.config import Config  # noqa: E402
from lolping.overlay import OverlayWindow  # noqa: E402


class _FixedCursor:
    def __init__(self, point: QPoint) -> None:
        self._point = QPoint(point)

    def pos(self) -> QPoint:
        return QPoint(self._point)


class TestActions(unittest.TestCase):
    def test_mapping(self) -> None:
        self.assertEqual(actions.sector_action("Enemy Missing"), actions.CAPTURE_REGION)
        self.assertEqual(actions.sector_action("On My Way"), actions.OPEN_SEARCH)
        self.assertIsNone(actions.sector_action("Push"))
        self.assertIsNone(actions.sector_action(""))

    def test_search_url_quotes_the_query(self) -> None:
        url = actions.search_url("On My Way")
        self.assertTrue(url.startswith("https://"))
        self.assertIn("On+My+Way", url)


class TestIntent(unittest.TestCase):
    def test_record_round_trip(self) -> None:
        record = intent.make_record(
            sector=4, name="Enemy Missing", action=actions.CAPTURE_REGION,
            x=100, y=200, region=(10, 20, 640, 360), screenshot="C:/tmp/x.png",
        )
        self.assertEqual(record["sector"], 4)
        self.assertEqual(record["region"], [10, 20, 640, 360])
        folder = Path(__file__).resolve().parents[1] / ".testtmp" / "dsh-intents"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            target = folder / "intents.jsonl"
            if target.exists():
                target.unlink()
            intent.append_intent(record, target)
            intent.append_intent(record, target)
            lines = target.read_text(encoding="utf-8").splitlines()
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["action"], actions.CAPTURE_REGION)

    def test_missing_screenshot_flag(self) -> None:
        record = intent.make_record(sector=0, name="On My Way", action=actions.OPEN_SEARCH,
                                    x=1, y=2)
        self.assertIsNone(record["region"])
        self.assertEqual(record["screenshot"], "")


class TestDshTiming(unittest.TestCase):
    def test_dsh_waits_for_the_commit_animation(self) -> None:
        from lolping import app as app_module

        config = Config()
        delay = app_module.dsh_delay_ms(config)
        self.assertGreaterEqual(delay, config.mark_duration_ms)
        self.assertGreaterEqual(delay, 400)


class TestConfig(unittest.TestCase):
    def test_dsh_mode_round_trip(self) -> None:
        self.assertFalse(Config().dsh_mode)
        self.assertTrue(Config.from_dict({"dsh_mode": True}).dsh_mode)
        self.assertFalse(Config.from_dict({"dsh_mode": "yes"}).dsh_mode)


class TestDshOverlay(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])
        self._saved_cursor = overlay_module.QCursor
        self.windows = []

    def tearDown(self) -> None:
        overlay_module.QCursor = self._saved_cursor
        for window in self.windows:
            window.shutdown()

    def _hover(self, dsh: bool, point: QPoint) -> int:
        window = OverlayWindow(
            self.app.primaryScreen(), Config(theme="jarvis", wheel_radius=130, dsh_mode=dsh)
        )
        window._center = QPoint(300, 300)
        overlay_module.QCursor = _FixedCursor(point)
        self.windows.append(window)
        return window._hovered_sector()

    def _point_for(self, index: int, radius: float = 110.0) -> QPoint:
        import math

        angle = math.radians(index * 45.0)
        return QPoint(int(300 + radius * math.cos(angle)), int(300 + radius * math.sin(angle)))

    def test_dsh_mode_blocks_slices_without_an_action(self) -> None:
        push = self._point_for(7)  # Push: no injected action
        missing = self._point_for(4)  # Enemy Missing: capture action
        self.assertEqual(self._hover(False, push), 7)
        self.assertEqual(self._hover(True, push), -1)
        self.assertEqual(self._hover(True, missing), 4)

    def test_dsh_mode_paints_dimmed_wheel(self) -> None:
        window = OverlayWindow(
            self.app.primaryScreen(), Config(theme="jarvis", wheel_radius=130, dsh_mode=True)
        )
        self.windows.append(window)
        window._center = QPoint(200, 200)
        window._open = True
        window._opened_at = 0.0
        image = QImage(400, 400, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        try:
            window._paint_wheel(painter, 1.0)
        finally:
            painter.end()
        alpha = sum(image.pixelColor(x, 200).alpha() for x in range(60, 340, 20))
        self.assertGreater(alpha, 0)


if __name__ == "__main__":
    unittest.main()
