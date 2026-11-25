"""Tests for the jarvis theme drawing path (offscreen)."""

from __future__ import annotations

import time
import unittest

from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication

from lolping import assets, geo
from lolping.config import Config
from lolping.overlay import OverlayWindow


class TestJarvisChoreography(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])
        self.window = OverlayWindow(
            self.app.primaryScreen(), Config(theme="jarvis", wheel_radius=130)
        )
        self.window._jarvis_mode = "open"
        self.window._jarvis_mode_start = 0.0
        self.window._jarvis_rot = [120.0, 120.0, 40.0]
        self.window._jarvis_shift = 0.0

    def tearDown(self) -> None:
        self.window.shutdown()

    def test_drag_shrinks_all_rings_to_sixty_degrees(self) -> None:
        self.window._jarvis_start_focus(0.1, 90.0)
        windows, opacity, scale = self.window._jarvis_windows(0.6)
        for start, end in windows:
            self.assertAlmostEqual(end - start, 60.0, places=3)
            self.assertAlmostEqual((start + end) / 2.0, 90.0, places=3)
        self.assertAlmostEqual(opacity, 1.0, places=6)
        self.assertEqual(scale, 1.0)

    def test_commit_shrinks_to_the_slice_span_then_fades(self) -> None:
        self.window._jarvis_start_focus(0.1, 90.0)
        self.window._jarvis_start_commit(0.6, 90.0)
        windows, opacity, _scale = self.window._jarvis_windows(0.8)
        for start, end in windows:
            self.assertAlmostEqual(end - start, 45.0, places=3)
            self.assertAlmostEqual((start + end) / 2.0, 90.0, places=3)
        self.assertAlmostEqual(opacity, 1.0, places=6)
        windows, opacity, _scale = self.window._jarvis_windows(0.9)
        self.assertLess(opacity, 1.0)
        self.assertGreater(opacity, 0.0)

    def test_cancel_restores_then_fades(self) -> None:
        self.window._jarvis_start_focus(0.1, 90.0)
        self.window._jarvis_start_cancel(0.6)
        windows, opacity, _scale = self.window._jarvis_windows(0.9)
        spans = [end - start for start, end in windows]
        self.assertAlmostEqual(spans[0], 150.0, places=2)
        self.assertAlmostEqual(spans[1], 90.0, places=2)
        self.assertAlmostEqual(opacity, 1.0, places=6)
        _windows, opacity, _scale = self.window._jarvis_windows(1.4)
        self.assertLess(opacity, 1.0)

    def test_centre_ping_collapses_and_fades_together(self) -> None:
        self.window._jarvis_start_centre(0.0)
        _windows, opacity, scale = self.window._jarvis_windows(0.25)
        self.assertAlmostEqual(scale, 1.0 - self.window._jarvis_ease(0.5), places=2)
        self.assertLess(opacity, 1.0)
        _windows, opacity, scale = self.window._jarvis_windows(0.6)
        self.assertEqual(opacity, 0.0)
        self.assertEqual(scale, 0.0)


class TestRotationPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])
        self.window = OverlayWindow(
            self.app.primaryScreen(), Config(theme="jarvis", wheel_radius=130)
        )

    def tearDown(self) -> None:
        self.window.shutdown()

    def test_begin_keeps_the_ring_angle(self) -> None:
        import time as _time

        self.window._jarvis_rot = [10.0, 20.0, 30.0]
        self.window._jarvis_shift = 7.0
        self.window._jarvis_last = _time.perf_counter()
        self.window.begin(QPoint(400, 300))
        # No hidden-time gap: the stored angles must survive the reopen.
        self.assertAlmostEqual(self.window._jarvis_rot[0], 10.0, delta=0.5)
        self.assertAlmostEqual(self.window._jarvis_shift, 7.0, delta=0.5)
        self.window.cancel()

    def test_hidden_time_still_advances_the_rings(self) -> None:
        import time as _time

        self.window._jarvis_rot = [0.0, 0.0, 0.0]
        self.window._jarvis_shift = 0.0
        self.window._jarvis_last = _time.perf_counter() - 10.0
        self.window.begin(QPoint(400, 300))
        self.assertAlmostEqual(self.window._jarvis_rot[0], 30.0, delta=2.0)
        self.assertAlmostEqual(self.window._jarvis_rot[1], 75.0, delta=2.0)
        self.assertAlmostEqual(self.window._jarvis_shift, 30.0, delta=2.0)
        self.window.cancel()


class TestLabelCache(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])

    def test_warm_labels_builds_the_glyph_cache(self) -> None:
        from PyQt5.QtGui import QColor, QImage, QPainter

        from lolping.jarvis import JarvisRenderer

        renderer = JarvisRenderer()
        renderer.warm_labels(130.0)
        self.assertGreater(len(renderer._glyphs), 10)
        self.assertTrue(renderer._fonts)
        self.assertTrue(renderer._arc_layouts)

        image = QImage(400, 400, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        try:
            font = renderer._font_pair(max(5, int(round(130.0 * 0.045))))[0]
            renderer._draw_arc_text(painter, 200.0, 200.0, 90.0, 130.0,
                                    "Victoria", font, QColor(255, 255, 255, 200))
            after_first = len(renderer._glyphs)
            renderer._draw_arc_text(painter, 200.0, 200.0, 90.0, 130.0,
                                    "Victoria", font, QColor(255, 255, 255, 200))
        finally:
            painter.end()
        self.assertEqual(len(renderer._glyphs), after_first)


class TestSearchFrames(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])
        self.window = OverlayWindow(
            self.app.primaryScreen(),
            Config(theme="jarvis", wheel_radius=130, dsh_mode=True),
        )
        self.window._center = QPoint(450, 450)
        self.window._hover = 0  # On My Way = injected search slice

    def tearDown(self) -> None:
        self.window.shutdown()

    def test_frames_fade_in_while_the_search_slice_is_hovered(self) -> None:
        self.window._search_frames_alpha = 0.0
        self.window._advance_search_frames(0.05)
        self.assertGreater(self.window._search_frames_alpha, 0.0)
        self.window._advance_search_frames(0.5)
        self.assertAlmostEqual(self.window._search_frames_alpha, 1.0, places=3)

    def test_frames_fade_out_when_the_slice_is_left(self) -> None:
        self.window._search_frames_alpha = 1.0
        self.window._hover = 2  # not the search slice
        self.window._advance_search_frames(0.5)
        self.assertAlmostEqual(self.window._search_frames_alpha, 0.0, places=3)

    def test_hold_keeps_the_frames_up(self) -> None:
        self.window._hover = -1
        self.window._search_frames_hold = True
        self.window._advance_search_frames(0.5)
        self.assertAlmostEqual(self.window._search_frames_alpha, 1.0, places=3)

    def test_frames_paint_visible_edges(self) -> None:
        from PyQt5.QtGui import QColor, QImage, QPainter

        self.window._search_frames_alpha = 1.0
        image = QImage(900, 900, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        try:
            self.window._paint_search_frames(painter, 0.0)
        finally:
            painter.end()
        local = self.window.mapFromGlobal(QPoint(450, 450))
        left = int(local.x() - 320)
        top = int(local.y() - 180)
        edge_alpha = max(
            image.pixelColor(left + 3, top).alpha(),
            image.pixelColor(left, top + 3).alpha(),
        )
        self.assertGreater(edge_alpha, 0)


class TestLandmarkGating(unittest.TestCase):
    def setUp(self) -> None:
        from lolping.jarvis import JarvisRenderer

        self.renderer = JarvisRenderer()
        self.name = geo.LANDMARKS[0][0]
        self.angle = geo.angle_for_lon(geo.LANDMARKS[0][2])

    def test_label_enters_only_inside_the_animated_lens(self) -> None:
        self.renderer._update_state(0.0, 0.0, [(self.angle - 5.0, self.angle + 5.0)])
        self.assertTrue(self.renderer._states[self.name].entering)
        # The lens moves away: the label must start leaving, not keep showing.
        self.renderer._update_state(0.1, 0.0, [(self.angle + 90.0, self.angle + 135.0)])
        self.assertFalse(self.renderer._states[self.name].entering)

    def test_label_returns_when_the_lens_covers_it_again(self) -> None:
        self.renderer._update_state(0.0, 0.0, [(self.angle - 5.0, self.angle + 5.0)])
        self.renderer._update_state(0.1, 0.0, [(self.angle + 90.0, self.angle + 135.0)])
        self.assertFalse(self.renderer._states[self.name].entering)
        self.renderer._update_state(0.2, 0.0, [(self.angle - 5.0, self.angle + 5.0)])
        self.assertTrue(self.renderer._states[self.name].entering)


class TestFadeOpacity(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])

    def _paint(self, opacity: float):
        import math

        from PyQt5.QtGui import QColor, QImage, QPainter

        from lolping.jarvis import JarvisRenderer

        renderer = JarvisRenderer()
        image = QImage(600, 600, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        try:
            renderer.draw(
                painter, 300.0, 300.0, 120.0, 0.0,
                windows=((120.0, 270.0), (120.0, 210.0), (40.0, 130.0)),
                data_shift=0.0, opacity=opacity, backdrop=0.0,
            )
        finally:
            painter.end()
        alphas = []
        for step in range(24):
            angle = step / 24.0 * math.tau
            x = int(300 + 1.45 * 120 * math.cos(angle))
            y = int(300 + 1.45 * 120 * math.sin(angle))
            alphas.append(image.pixelColor(x, y).alpha())
        return alphas

    def test_zero_opacity_hides_the_textures(self) -> None:
        self.assertTrue(all(alpha == 0 for alpha in self._paint(0.0)))

    def test_full_opacity_draws_the_textures(self) -> None:
        self.assertGreater(max(self._paint(1.0)), 0)


class TestJarvisTheme(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])
        self.window = OverlayWindow(
            self.app.primaryScreen(), Config(theme="jarvis", wheel_radius=130)
        )

    def tearDown(self) -> None:
        self.window.shutdown()

    def _paint(self) -> QImage:
        self.window._center = QPoint(400, 300)
        self.window._open = True
        self.window._opened_at = time.perf_counter() - 1.0
        image = QImage(800, 600, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        try:
            self.window._paint_wheel(painter, time.perf_counter())
        finally:
            painter.end()
        return image

    def test_theme_paints_ring_content(self) -> None:
        image = self._paint()
        # the baked bands live well outside the wheel rim
        alpha_sum = sum(
            image.pixelColor(x, y).alpha()
            for x, y in ((400, 30), (760, 300), (400, 570), (40, 300))
        )
        self.assertGreater(alpha_sum, 0, "the jarvis bands painted nothing")

    def test_offscreen_platform_falls_back_to_procedural_frost(self) -> None:
        self.window.setGeometry(0, 0, 800, 600)
        self.window._center = QPoint(400, 300)
        frost = self.window._capture_frost()
        # The offscreen plugin may or may not provide a grab; either way it must
        # not raise and the renderer must cope with both outcomes.
        self.assertTrue(frost is None or frost.width() > 0)

    def test_missing_textures_degrade_gracefully(self) -> None:
        saved = dict(assets._JARVIS_CACHE)
        try:
            assets._JARVIS_CACHE["contours"] = None
            assets._JARVIS_CACHE["isotherms"] = None
            image = self._paint()
            self.assertGreater(image.pixelColor(400, 300).alpha(), 0)
        finally:
            assets._JARVIS_CACHE.clear()
            assets._JARVIS_CACHE.update(saved)


if __name__ == "__main__":
    unittest.main()
