"""Tests for lolping.geo (pure angular model and data sources)."""

from __future__ import annotations

import unittest

from lolping import geo


class TestMapping(unittest.TestCase):
    def test_longitude_maps_to_a_full_turn(self) -> None:
        self.assertAlmostEqual(geo.angle_for_lon(geo.LON_MIN), 0.0, places=6)
        self.assertAlmostEqual(geo.angle_for_lon(geo.LON_MAX), 360.0, places=6)

    def test_longitude_outside_the_box_is_clamped(self) -> None:
        self.assertEqual(geo.angle_for_lon(geo.LON_MIN - 1.0), 0.0)
        self.assertEqual(geo.angle_for_lon(geo.LON_MAX + 1.0), 360.0)

    def test_latitude_maps_inside_the_requested_band(self) -> None:
        low = geo.radius_factor(geo.LAT_MIN, geo.BAND_INNER)
        high = geo.radius_factor(geo.LAT_MAX, geo.BAND_INNER)
        self.assertAlmostEqual(low, geo.BAND_INNER[0], places=6)
        self.assertAlmostEqual(high, geo.BAND_INNER[1], places=6)


class TestIntervals(unittest.TestCase):
    def test_window_spans_match_each_ring(self) -> None:
        start, end = geo.window(geo.PHASE_INNER, 0.0, geo.SPEED_INNER,
                                geo.WINDOW_SPAN_INNER)
        self.assertAlmostEqual(end - start, 150.0, places=6)
        self.assertAlmostEqual(start, geo.PHASE_INNER, places=6)
        start, end = geo.window(geo.PHASE_MIDDLE, 0.0, geo.SPEED_MIDDLE)
        self.assertAlmostEqual(end - start, 90.0, places=6)

    def test_ring_data_drifts_at_three_degrees_per_second(self) -> None:
        self.assertAlmostEqual(geo.TEXTURE_SPEED, 3.0, places=6)

    def test_middle_speed_is_a_quarter_faster(self) -> None:
        self.assertAlmostEqual(geo.SPEED_MIDDLE, 7.5, places=6)

    def test_window_wraps_past_three_sixty(self) -> None:
        start, end = geo.window(340.0, 10.0, 1.0)
        self.assertGreater(start, 300.0)
        self.assertGreater(end, 360.0)

    def test_in_interval_respects_the_feather(self) -> None:
        self.assertEqual(geo.in_interval(105.0, 100.0, 190.0, feather=5.0), 1.0)
        self.assertEqual(geo.in_interval(98.0, 100.0, 190.0, feather=5.0), 0.0)
        partial = geo.in_interval(102.0, 100.0, 190.0, feather=5.0)
        self.assertGreater(partial, 0.0)
        self.assertLess(partial, 1.0)

    def test_overlap_of_identical_windows_is_the_whole_window(self) -> None:
        window = geo.window(geo.PHASE_INNER, 0.0, geo.SPEED_INNER)
        pieces = geo.overlap_intervals(window, window)
        self.assertEqual(len(pieces), 1)
        self.assertAlmostEqual(pieces[0][1] - pieces[0][0], geo.WINDOW_SPAN, places=6)

    def test_opposite_windows_do_not_overlap(self) -> None:
        self.assertEqual(geo.overlap_intervals((0.0, 90.0), (180.0, 270.0)), [])

    def test_overlap_can_wrap_around_zero(self) -> None:
        pieces = geo.overlap_intervals((300.0, 390.0), (330.0, 420.0))
        self.assertTrue(pieces)
        total = sum(end - start for start, end in pieces)
        self.assertAlmostEqual(total, 60.0, places=6)

    def test_lens_is_the_middle_window_over_the_inner_one(self) -> None:
        inner = geo.window(geo.PHASE_INNER, 15.0, geo.SPEED_INNER,
                           geo.WINDOW_SPAN_INNER)
        middle = geo.window(geo.PHASE_MIDDLE, 15.0, geo.SPEED_MIDDLE)
        lens = geo.lens_intervals(inner, middle)
        total = sum(end - start for start, end in lens)
        # inner [165, 315] (150 deg) vs middle [232.5, 322.5] (7.5 deg/s)
        self.assertAlmostEqual(total, 82.5, places=6)


class TestRevealTiming(unittest.TestCase):
    def test_line_grows_before_the_name(self) -> None:
        line, visible, _ = geo.reveal_progress(geo.LINE_SECONDS * 0.5, entering=True)
        self.assertGreater(line, 0.0)
        self.assertLess(line, 1.0)
        self.assertEqual(visible, 0.0)

    def test_name_is_up_after_the_line(self) -> None:
        line, visible, _ = geo.reveal_progress(geo.LINE_SECONDS + geo.NAME_SECONDS, entering=True)
        self.assertEqual(line, 1.0)
        self.assertEqual(visible, 1.0)

    def test_leaving_plays_the_sequence_backwards(self) -> None:
        line, visible, _ = geo.reveal_progress(0.0, entering=False)
        self.assertEqual(visible, 1.0)
        later, later_visible, _ = geo.reveal_progress(
            geo.LINE_SECONDS + geo.NAME_SECONDS + geo.LEAVE_SECONDS * 0.5, entering=False
        )
        self.assertLess(later, 1.0)
        self.assertLess(later_visible, 1.0)

    def test_fully_left_reveals_nothing(self) -> None:
        total = geo.LINE_SECONDS + geo.NAME_SECONDS + geo.LEAVE_SECONDS
        self.assertEqual(geo.reveal_progress(total + 0.01, entering=False), (0.0, 0.0, 0.0))


class TestDataSources(unittest.TestCase):
    def test_landmarks_lie_inside_the_hong_kong_box(self) -> None:
        self.assertGreaterEqual(len(geo.LANDMARKS), 10)
        for name, lat, lon, kind in geo.LANDMARKS:
            self.assertGreaterEqual(lon, geo.LON_MIN, name)
            self.assertLessEqual(lon, geo.LON_MAX, name)
            self.assertGreaterEqual(lat, geo.LAT_MIN, name)
            self.assertLessEqual(lat, geo.LAT_MAX, name)
            self.assertIn(kind, {"b", "s", "r"})

    def test_weather_samples_have_real_values(self) -> None:
        self.assertEqual(len(geo.WEATHER), 3)
        for lat, lon, temp, wind, direction in geo.WEATHER:
            self.assertGreaterEqual(lon, geo.LON_MIN)
            self.assertLessEqual(lon, geo.LON_MAX)
            self.assertTrue(20.0 <= temp <= 35.0)
            self.assertTrue(0.0 <= wind <= 120.0)
            self.assertTrue(0.0 <= direction <= 360.0)

    def test_contours_and_isotherms_are_produced(self) -> None:
        contours = list(geo.contour_segments(100.0))
        isotherms = list(geo.isotherm_segments(1.0))
        self.assertGreater(len(contours), 100)
        self.assertGreater(len(isotherms), 20)


if __name__ == "__main__":
    unittest.main()
