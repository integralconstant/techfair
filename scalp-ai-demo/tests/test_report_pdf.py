"""PDF payload boundaries, Korean embedding and grade consistency."""
from __future__ import annotations

import copy
import importlib.util
import math
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import report_pdf
from report_pdf import ReportFontError, ReportValidationError, build_report_pdf, report_data


def result_fixture(count=1):
    metrics = []
    for model_id in report_pdf.METRIC_IDS:
        values = [0.4, 0.3, 0.2, 0.1] if model_id == "flakes" else [0.4, 0.35, 0.25]
        metrics.append({"id": model_id, "probabilities": values, "label": "do not trust this label",
                        "preprocessing_version": report_pdf.CURRENT_FLAKES if model_id == "flakes" else report_pdf.CURRENT_SEBUM if model_id == "sebum" else None})
    return {"source": "model", "date": "2026-11-03", "photo_count": count, "aggregation": "mean_probabilities",
            "metrics": metrics, "per_photo": [{"index": index, "metrics": copy.deepcopy(metrics)} for index in range(count)]}


class ReportValidationTests(unittest.TestCase):
    def test_merge_before_argmax_matches_web_instead_of_untrusted_labels(self):
        data = report_data(result_fixture())
        self.assertEqual([metric["label"] for metric in data["metrics"]], ["경중등도", "유", "정상", "정상"])
        self.assertEqual(data["metrics"][1]["name"], "피지 유무")
        self.assertFalse(data["legacy"])

    def test_legacy_sebum_and_flakes_are_identified_without_rewriting_saved_input(self):
        result = result_fixture()
        result["metrics"][1].pop("preprocessing_version")
        result["metrics"][0].pop("preprocessing_version")
        before = copy.deepcopy(result)
        data = report_data(result)
        self.assertEqual(data["metrics"][1]["label"], "정상")
        self.assertIn("이전 기준", data["metrics"][1]["name"])
        self.assertTrue(data["legacy"])
        self.assertEqual(result, before)

    def test_ties_choose_first_displayed_grade(self):
        result = result_fixture()
        result["metrics"][1]["probabilities"] = [0.5, 0.25, 0.25]
        self.assertEqual(report_data(result)["metrics"][1]["label"], "무")

    def test_invalid_result_envelope_is_rejected(self):
        for change in ({"source": "sample"}, {"date": "2026-02-30"}, {"date": "2026-1-1"},
                       {"photo_count": True}, {"photo_count": 0}, {"photo_count": 4},
                       {"aggregation": "median"}, {"per_photo": []}):
            with self.subTest(change=change), self.assertRaises(ReportValidationError):
                report_data({**result_fixture(), **change})

    def test_invalid_metric_probabilities_are_rejected(self):
        for values in ([1], [0, 0, 0], [True, 0, 0], [math.nan, 0, 0], [math.inf, 0, 0],
                       [-0.1, 0.5, 0.6], [10 ** 500, 0, 0], ["0.4", 0.3, 0.3]):
            result = result_fixture()
            result["metrics"][1]["probabilities"] = values
            with self.subTest(values=str(values)[:100]), self.assertRaises(ReportValidationError):
                report_data(result)

    def test_unknown_duplicate_or_reordered_metrics_are_rejected(self):
        for bad_id in ("unknown", "flakes", "erythema"):
            result = result_fixture()
            result["metrics"][1]["id"] = bad_id
            with self.subTest(bad_id=bad_id), self.assertRaises(ReportValidationError):
                report_data(result)

    def test_per_photo_results_are_validated_instead_of_trusting_summary(self):
        for change in ({"index": True}, {"index": 2}, {"metrics": []}):
            result = result_fixture()
            result["per_photo"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ReportValidationError):
                report_data(result)


class PdfOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            regular, _ = report_pdf._font_paths()
        except ReportFontError as exc:
            raise unittest.SkipTest(str(exc))
        cls.pdf = build_report_pdf(result_fixture(3), {"nickname": "두피 <회원>&"})

    def test_pdf_is_memory_bytes_and_embeds_true_type_font(self):
        self.assertIsInstance(self.pdf, bytes)
        self.assertTrue(self.pdf.startswith(b"%PDF-"))
        self.assertIn(b"/FontFile2", self.pdf)
        self.assertIn(b"/ToUnicode", self.pdf)
        self.assertLess(len(self.pdf), 2 * 1024 * 1024)

    @unittest.skipUnless(importlib.util.find_spec("pymupdf"), "PyMuPDF available for optional PDF text verification")
    def test_korean_text_and_per_photo_results_are_readable_without_percentages(self):
        import pymupdf
        with pymupdf.open(stream=self.pdf, filetype="pdf") as document:
            text = "".join(page.get_text() for page in document)
            self.assertLessEqual(len(document), 2)
            self.assertIn("나의 두피 분석 보고서", text)
            self.assertIn("경중등도", text)
            self.assertIn("모낭사이홍반", text)
            self.assertIn("두피 <회원>&", text)
            self.assertIn("사진별 분석 결과", text)
            self.assertNotIn("do not trust", text)
            self.assertNotIn("%", text)
            self.assertNotIn("confidence", text)
            self.assertNotIn("preprocessing", text)
            for page in document:
                for block in page.get_text("blocks"):
                    self.assertGreaterEqual(block[0], 0)
                    self.assertLessEqual(block[2], page.rect.width + 1)
                    self.assertGreaterEqual(block[1], 0)
                    self.assertLessEqual(block[3], page.rect.height + 1)

    def test_missing_configured_font_has_friendly_error_instead_of_silent_fallback(self):
        with patch.dict(os.environ, {"SCALP_PDF_FONT": str(Path.cwd() / "no-such-korean-font.ttf")}), \
             patch.object(report_pdf.pdfmetrics, "getRegisteredFontNames", return_value=[]):
            with self.assertRaises(ReportFontError):
                build_report_pdf(result_fixture())


if __name__ == "__main__":
    unittest.main()
