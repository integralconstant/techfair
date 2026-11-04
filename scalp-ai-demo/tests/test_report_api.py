"""Direct PDF download HTTP contract and account boundary checks."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import create_app
from report_pdf import ReportFontError
from test_report_pdf import result_fixture


class ReadyService:
    def health(self):
        return {"status": "ready", "models": []}


class ReportApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.app = create_app(ReadyService(), database_path=Path(folder.name) / "accounts.sqlite3")
        self.client = self.app.test_client()

    def test_guest_download_is_pdf_attachment_with_private_cache_headers(self):
        response = self.client.post("/api/report/pdf", json={"result": result_fixture()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn(".pdf", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIsNone(self.client.get("/api/auth/me").json["user"])
        response.close()

    def test_invalid_payload_never_returns_pdf(self):
        for body in ({}, {"result": None}, {"result": {}}, {"result": {**result_fixture(), "photo_count": 99}}):
            with self.subTest(body=str(body)[:100]):
                response = self.client.post("/api/report/pdf", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json)

    def test_json_size_and_same_origin_are_enforced(self):
        self.assertEqual(self.client.post("/api/report/pdf", data="result=hello").status_code, 415)
        self.assertEqual(self.client.post("/api/report/pdf", json={"result": result_fixture()}, headers={"Origin": "https://foreign.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/report/pdf", json={"padding": "x" * (513 * 1024)}).status_code, 413)

    def test_stale_account_or_profile_cannot_download_under_new_identity(self):
        user = self.client.post("/api/auth/register", json={"nickname": "PDF회원", "password": "new-pass"}).json["user"]
        stale = {"X-Scalp-Account": str(user["id"]), "X-Scalp-Result-Epoch": str(user["result_epoch"]), "X-Scalp-Profile-Version": str(user["profile_version"])}
        changed = self.client.patch("/api/auth/profile", json={"current_password": "new-pass", "nickname": "PDF새아이디"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.post("/api/report/pdf", json={"result": result_fixture()}, headers=stale).status_code, 409)
        self.assertEqual(self.client.post("/api/report/pdf", json={"result": result_fixture()}, headers={"X-Scalp-Account": "guest"}).status_code, 409)

    def test_missing_korean_font_has_friendly_error(self):
        with patch("report_pdf.build_report_pdf", side_effect=ReportFontError("font absent")), self.assertLogs(self.app.logger.name, level="ERROR"):
            response = self.client.post("/api/report/pdf", json={"result": result_fixture()})
        self.assertEqual(response.status_code, 503)
        self.assertIn("한글 글꼴", response.json["error"])
        self.assertNotIn("font absent", response.json["error"])
