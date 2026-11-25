"""Settings window: night mode, Apply semantics and live preview."""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QPixmap  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from lolping.config import Config  # noqa: E402
from lolping.settings_dialog import SettingsDialog, WheelPreview  # noqa: E402


class TestSettingsLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.applied: list[Config] = []
        self.dialog = SettingsDialog(Config(), None, on_apply=self.applied.append)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        self.dialog._preview.shutdown()
        self.dialog.deleteLater()

    def test_night_mode_round_trip(self) -> None:
        self.assertFalse(Config().settings_night_mode)
        self.assertTrue(Config.from_dict({"settings_night_mode": True}).settings_night_mode)

    def test_night_mode_restyles_the_window(self) -> None:
        self.dialog._night_check.setChecked(True)
        self.assertIn("background-color: #14161b", self.dialog.styleSheet())
        self.dialog._night_check.setChecked(False)
        self.assertEqual(self.dialog.styleSheet(), "")

    def test_apply_keeps_the_dialog_open_and_calls_back(self) -> None:
        self.dialog._dsh_check.setChecked(True)
        self.dialog._apply_button.click()
        self.assertEqual(len(self.applied), 1)
        self.assertTrue(self.applied[0].dsh_mode)
        self.assertEqual(self.dialog.result(), 0)  # not accepted/closed
        self.assertEqual(self.dialog._error_label.text(), "Applied")

    def test_apply_persists_night_mode_in_the_config(self) -> None:
        self.dialog._night_check.setChecked(True)
        self.dialog._apply_button.click()
        self.assertTrue(self.applied[-1].settings_night_mode)

    def test_preview_animation_loops_through_the_steps(self) -> None:
        preview = WheelPreview(Config())
        self.addCleanup(preview.shutdown)
        names = []
        for _ in range(len(WheelPreview._STEPS)):
            names.append(WheelPreview._STEPS[preview._state_index][0])
            preview._state_start = time.perf_counter() - 10.0
            preview._advance()
        self.assertEqual(
            names, ["wake", "idle", "select", "idle", "deselect", "exit"]
        )
        self.assertEqual(preview._state_index, 0)

    def test_preview_pauses_on_the_wheel_signal_and_resumes(self) -> None:
        preview = WheelPreview(Config())
        self.addCleanup(preview.shutdown)
        preview.set_wheel_active(True)
        self.assertTrue(preview._paused)
        self.assertFalse(preview._anim.isActive())
        index = preview._state_index
        preview._state_start = time.perf_counter() - 10.0
        preview._advance()
        self.assertEqual(preview._state_index, index)
        preview.set_wheel_active(False)
        self.assertFalse(preview._paused)
        self.assertTrue(preview._anim.isActive())

    def test_dialog_preview_follows_the_wheel_activity_signal(self) -> None:
        from PyQt5.QtCore import QPoint

        from lolping.overlay import OverlayManager

        manager = OverlayManager(Config())
        self.addCleanup(manager.shutdown)
        events: list[bool] = []
        manager.wheel_active_changed.connect(events.append)
        dialog = SettingsDialog(Config(), None, wheel_activity=manager.wheel_active_changed)
        self.addCleanup(self._close_dialog, dialog)
        manager.begin_at(QPoint(200, 200))
        self.assertEqual(events, [True])
        self.assertTrue(dialog._preview._paused)
        manager.hide_all()
        self.assertEqual(events, [True, False])
        self.assertFalse(dialog._preview._paused)

    @staticmethod
    def _close_dialog(dialog: SettingsDialog) -> None:
        dialog._preview.shutdown()
        dialog.deleteLater()

    def test_preview_renders_a_wheel(self) -> None:
        preview = WheelPreview(Config())
        self.addCleanup(preview.shutdown)
        pixmap = QPixmap(preview.SIZE, preview.SIZE)
        pixmap.fill(Qt.transparent)
        preview.render(pixmap)
        self.assertFalse(pixmap.isNull())


if __name__ == "__main__":
    unittest.main()
