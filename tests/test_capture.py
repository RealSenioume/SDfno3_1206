"""Field fixes: edge-centred capture and frozen asset lookup."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt5.QtCore import QPoint, QRect  # noqa: E402
from PyQt5.QtGui import QColor, QImage, QPixmap  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from lolping import assets, intent  # noqa: E402

SCRATCH = Path(__file__).resolve().parents[1] / ".testtmp" / "capture-test"


class _FakeScreen:
    """1000x800 screen filled with one colour."""

    def __init__(self, colour: str = "#c83c3c") -> None:
        self._colour = QColor(colour)

    def geometry(self) -> QRect:
        return QRect(0, 0, 1000, 800)

    def devicePixelRatio(self) -> float:
        return 1.0

    def grabWindow(self, *args) -> QPixmap:  # noqa: ARG002
        pixmap = QPixmap(1000, 800)
        pixmap.fill(self._colour)
        return pixmap


class TestCentredCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.path = SCRATCH / "shot.png"

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_corner_capture_keeps_the_point_in_the_centre(self) -> None:
        ok = intent.capture_centered(_FakeScreen(), QPoint(10, 10), 640, 360, self.path)
        self.assertTrue(ok)
        image = QImage(str(self.path))
        self.assertEqual((image.width(), image.height()), (640, 360))
        centre = image.pixelColor(320, 180)
        corner = image.pixelColor(2, 2)
        self.assertGreater(centre.red(), 150)
        self.assertLess(corner.red(), 40)  # off-screen margin is padded black

    def test_middle_capture_is_all_screen(self) -> None:
        ok = intent.capture_centered(_FakeScreen(), QPoint(500, 400), 640, 360, self.path)
        self.assertTrue(ok)
        image = QImage(str(self.path))
        self.assertGreater(image.pixelColor(2, 2).red(), 150)
        self.assertGreater(image.pixelColor(637, 357).red(), 150)


class TestFrozenAssets(unittest.TestCase):
    def test_frozen_dirs_include_meipass_and_internal(self) -> None:
        saved = (getattr(sys, "_MEIPASS", None), getattr(sys, "frozen", None),
                 getattr(sys, "executable", None))
        try:
            sys._MEIPASS = r"C:\tmp\meipass"
            sys.frozen = True
            sys.executable = r"C:\tmp\lolping\lolping.exe"
            dirs = assets.frozen_asset_dirs()
            joined = [str(item) for item in dirs]
            self.assertTrue(any("meipass" in item for item in joined))
            self.assertTrue(any("_internal" in item for item in joined))
        finally:
            for name, value in zip(("_MEIPASS", "frozen", "executable"), saved):
                if value is None:
                    if hasattr(sys, name):
                        delattr(sys, name)
                else:
                    setattr(sys, name, value)


if __name__ == "__main__":
    unittest.main()
