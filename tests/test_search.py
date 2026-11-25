"""Tests for OCR scoring and the text/image search routing."""

from __future__ import annotations

import unittest

from lolping import ocr, search


class TestSearchDecision(unittest.TestCase):
    def test_high_confidence_goes_text(self) -> None:
        decision = search.decide("Victoria Harbour", 82)
        self.assertEqual(decision.mode, "text")
        self.assertEqual(search.urls_for(decision), [search.text_search_url("Victoria Harbour")])

    def test_threshold_boundaries_are_60_and_25(self) -> None:
        self.assertEqual(search.decide("Victoria Harbour", 60).mode, "text")
        self.assertEqual(search.decide("Victoria Harbour", 59).mode, "both")
        self.assertEqual(search.decide("Victoria", 25).mode, "both")

    def test_middle_confidence_is_ambiguous(self) -> None:
        decision = search.decide("Bilibili", 45)
        self.assertEqual(decision.mode, "both")
        urls = search.urls_for(decision)
        self.assertEqual(len(urls), 1)
        self.assertIn("Bilibili", urls[0])

    def test_low_confidence_goes_image(self) -> None:
        self.assertEqual(search.decide("", 5).mode, "image")
        self.assertEqual(search.decide("x", 24).mode, "image")
        self.assertEqual(search.urls_for(search.decide("", 0)), [search.image_search_url()])

    def test_query_is_url_encoded(self) -> None:
        url = search.text_search_url("香港 維多利亞港")
        self.assertNotIn(" ", url)
        self.assertIn("%", url)


class TestQueryCleanupAndCentre(unittest.TestCase):
    def test_labels_and_icon_noise_are_stripped(self) -> None:
        self.assertEqual(ocr.clean_query("日 63RD"), "63RD")
        self.assertEqual(ocr.clean_query("Q 别 怕 变 老"), "别怕变老")
        self.assertEqual(ocr.clean_query("专辑：63RD 歌手：JOKER"), "63RD JOKER")

    def test_centre_line_beats_the_top_search_box(self) -> None:
        result = ocr.OCRResult(
            text="Q 别 怕 变 老 63RD",
            lines=["Q 别 怕 变 老", "63RD"],
            boxes=[(10.0, 4.0, 120.0, 18.0), (60.0, 80.0, 80.0, 18.0)],
            width=320,
            height=180,
        )
        score, query = ocr.usability(result)
        self.assertEqual(query, "63RD")
        self.assertGreater(score, 0)


class TestOCRScoring(unittest.TestCase):
    def test_clean_line_scores_high(self) -> None:
        self.assertGreaterEqual(ocr.line_score("Victoria Harbour"), 60)

    def test_noise_and_urls_score_low(self) -> None:
        self.assertLess(ocr.line_score("...."), 10)
        self.assertLess(ocr.line_score("https://www.bilibili.com/video/BV1"), 40)
        self.assertEqual(ocr.line_score("a"), 0)

    def test_spaced_cjk_is_normalised_before_scoring(self) -> None:
        self.assertEqual(ocr.normalize("弗 吉 尼 亚 州"), "弗吉尼亚州")
        self.assertGreaterEqual(ocr.line_score("弗 吉 尼 亚 州"), 60)

    def test_usability_uses_the_best_line(self) -> None:
        result = ocr.OCRResult(
            text="2026-11-25 16:20 维多利亚港 Victoria Harbour",
            lines=["2026-11-25 16:20", "维多利亚港", "Victoria Harbour"],
        )
        score, query = ocr.usability(result)
        self.assertGreater(score, 0)
        self.assertTrue(query)

    def test_empty_result_is_zero(self) -> None:
        self.assertEqual(ocr.usability(None), (0, ""))
        self.assertEqual(ocr.usability(ocr.OCRResult()), (0, ""))

    def test_single_weak_line_scores_lower_than_dense_text(self) -> None:
        one = ocr.usability(ocr.OCRResult(lines=["Victoria Harbour"]))[0]
        dense = ocr.usability(
            ocr.OCRResult(lines=["Victoria Harbour", "Hong Kong Island", "Central District"])
        )[0]
        self.assertGreater(dense, one)


class TestIntentFields(unittest.TestCase):
    def test_search_fields_are_persisted(self) -> None:
        from lolping import intent

        record = intent.make_record(
            sector=0, name="On My Way", action="open_search",
            x=1, y=2, text="Victoria Harbour", score=88, mode="text",
        )
        self.assertEqual(record["text"], "Victoria Harbour")
        self.assertEqual(record["score"], 88)
        self.assertEqual(record["mode"], "text")


if __name__ == "__main__":
    unittest.main()
