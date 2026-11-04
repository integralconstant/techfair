"""Exercise real SQLite persistence, session revocation and account isolation."""
from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path

from PIL import Image

from accounts import AccountStore, COOKIE_NAME, record_payload
from werkzeug.security import generate_password_hash
from server import create_app


class DemoService:
    def health(self):
        return {"status": "ready", "models": []}

    def analyze(self, images):
        metrics = []
        for index, model_id in enumerate(("flakes", "sebum", "hair_loss", "erythema")):
            values = [0.7, 0.1, 0.1, 0.1] if index == 0 else [0.7, 0.2, 0.1]
            labels = (["정상", "경증", "중등도", "중증"] if index == 0
                      else ["정상", "경증", "중등도이상"] if index == 1 else ["정상", "경증", "중증"])
            final_labels = (["무", "유"] if index == 1 else ["정상", "경중등도" if index == 0 else "경증", "중증"])
            metrics.append({"id": model_id, "name": model_id, "class_index": 0,
                            "label": final_labels[0], "confidence": 0.7,
                            "probabilities": values, "class_labels": labels, "settings_verified": index in (0, 1),
                            "labels_confirmed": True, "grade_index": 0, "excluded_classes": [],
                            "grade_probabilities": [0.7, 0.3] if index == 1 else [0.7, 0.2, 0.1],
                            "grade_labels": final_labels,
                            "grade_indices": [0, 1, 1, 2] if index == 0 else [0, 1, 1] if index == 1 else [0, 1, 2],
                            "grade_confidence": 0.7,
                            "grading_method": "probability_merge" if index in (0, 1) else "argmax",
                            "preprocessing_version": ("flakes-384-square-v1" if index == 0
                                                      else "sebum-384-attention-v1" if index == 1 else None)})
        return {"id": "analysis-123", "date": "2026-11-01", "source": "model", "photo_count": len(images),
                "aggregation": "mean_probabilities", "settings_verified": False, "warnings": [],
                "metrics": metrics, "per_photo": [{"index": i, "metrics": deepcopy(metrics)} for i in range(len(images))],
                "elapsed_ms": 100.5, "configuration_id": "test-config"}


class AccountApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "accounts.sqlite3"
        self.app = create_app(DemoService(), database_path=self.database)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.store = self.app.extensions["account_store"]

    def register(self, nickname="tester", password="246810", client=None):
        return (client or self.client).post("/api/auth/register", json={"nickname": nickname, "password": password})

    def analyze(self, client=None):
        stream = io.BytesIO()
        with Image.new("RGB", (8, 6), (80, 40, 20)) as image:
            image.save(stream, format="PNG")
        stream.seek(0)
        result = (client or self.client).post("/api/analyze", data={"photos": (stream, "private-photo.png")}, content_type="multipart/form-data")
        self.assertEqual(result.status_code, 200)
        return result.json

    def save(self, result, client=None):
        # The frontend omits metric.name, None preprocessing markers and transient fields.
        return (client or self.client).post("/api/records", json={"record": record_payload(result), "save_token": result["save_token"]})

    def test_registration_session_hash_and_cookie(self):
        self.assertIsNone(self.client.get("/api/auth/me").json["user"])
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["user"]["nickname"], "tester")
        self.assertEqual(self.client.get("/api/auth/me").json, response.json)
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Max-Age=604800", cookie)
        with self.store.connection() as db:
            stored_password = db.execute("SELECT password_hash FROM users").fetchone()[0]
            session_hash = db.execute("SELECT token_hash FROM sessions").fetchone()[0]
        self.assertNotEqual(stored_password, "246810")
        self.assertTrue(stored_password.startswith("scrypt:"))
        self.assertNotEqual(session_hash, self.client.get_cookie(COOKIE_NAME).value)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_duplicate_nickname_is_rejected_after_normalization_without_ui_precheck(self):
        first = self.register(nickname=" TestUser ").json["user"]
        for nickname in ("TestUser", "testuser", "ＴｅｓｔＵｓｅｒ"):
            response = self.register(nickname=nickname, password="135790")
            self.assertEqual(response.status_code, 409, response.json)
            self.assertEqual(response.json["code"], "nickname_taken")
            available = self.client.get("/api/auth/nickname", query_string={"nickname": nickname})
            self.assertFalse(available.json["available"])
        self.assertTrue(self.client.get("/api/auth/nickname?nickname=new-name").json["available"])
        self.assertEqual(self.client.get("/api/auth/nickname?nickname=").status_code, 400)
        logged_in = self.client.post("/api/auth/login", json={"nickname": "testuser", "password": "246810"})
        self.assertEqual(logged_in.json["user"], first)
        self.assertEqual(self.client.post("/api/auth/login", json={"nickname": "TestUser", "password": "wrong"}).status_code, 401)

    def test_historical_duplicate_accounts_keep_access_after_migration(self):
        first = self.register().json["user"]
        with self.store.connection() as db:
            cursor = db.execute("INSERT INTO users(nickname,password_hash,created_at) VALUES (?,?,?)",
                                ("tester", generate_password_hash("legacy-password"), int(time.time())))
            second_id = cursor.lastrowid
        migrated = AccountStore(self.database)
        self.assertEqual(migrated.login({"nickname": "tester", "password": "246810"})["id"], first["id"])
        self.assertEqual(migrated.login({"nickname": "tester", "password": "legacy-password"})["id"], second_id)
        self.assertEqual(self.register(password="new-password").status_code, 409)
        with migrated.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)

    def test_logout_revokes_replayed_cookie_and_expired_sessions(self):
        self.register()
        old_token = self.client.get_cookie(COOKIE_NAME).value
        self.assertEqual(self.client.post("/api/auth/logout", json={}).status_code, 200)
        self.client.set_cookie(COOKIE_NAME, old_token)
        self.assertIsNone(self.client.get("/api/auth/me").json["user"])
        self.client.post("/api/auth/login", json={"nickname": "tester", "password": "246810"})
        with self.store.connection() as db:
            db.execute("UPDATE sessions SET expires_at=?", (int(time.time()) - 1,))
        self.assertIsNone(self.client.get("/api/auth/me").json["user"])

    def test_account_endpoints_require_login(self):
        for method, path, body in [
            ("get", "/api/records", None), ("post", "/api/records", {}), ("delete", "/api/records", None),
            ("get", "/api/auth/profile", None), ("patch", "/api/auth/profile", {"current_password": "secret"}),
            ("get", "/api/care-checks?month=2026-11", None),
            ("get", "/api/care-checks?date=2026-11-01", None), ("put", "/api/care-checks", {"date": "2026-11-01", "checks": []}),
        ]:
            response = getattr(self.client, method)(path, **({"json": body} if body is not None else {}))
            self.assertEqual(response.status_code, 401, (method, path, response.json))

    def test_account_record_save_reload_idempotence_and_no_photos(self):
        self.register()
        result = self.analyze()
        saved = self.save(result)
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(saved.json["record"], record_payload(result))
        self.assertEqual(self.save(result).status_code, 200)
        records = self.client.get("/api/records").json["records"]
        self.assertEqual(records, [saved.json["record"]])
        self.assertNotIn("save_token", records[0])
        self.assertNotIn("private-photo", json.dumps(records))
        self.assertEqual(self.client.delete("/api/records").json, {"deleted": 1})
        self.assertEqual(self.client.get("/api/records").json, {"records": []})

    def test_existing_three_grade_sebum_record_is_preserved_without_binary_reinterpretation(self):
        user_id = self.register().json["user"]["id"]
        result = self.analyze()
        result["id"] = "legacy-sebum-three-grades"
        for metric in [result["metrics"][1], *[photo["metrics"][1] for photo in result["per_photo"]]]:
            metric.update(probabilities=[0.4, 0.35, 0.25], class_index=0, confidence=0.4,
                          label="정상", class_labels=["정상", "경증", "중증"], grade_index=0,
                          grade_probabilities=[0.4, 0.35, 0.25], grade_labels=["정상", "경증", "중증"],
                          grade_indices=[0, 1, 2], grade_confidence=0.4, grading_method="argmax",
                          settings_verified=False)
            metric.pop("preprocessing_version", None)
        result["save_token"] = self.store.sign_result(result, user_id)
        self.assertEqual(self.save(result).status_code, 201)
        stored = self.client.get("/api/records").json["records"][0]
        self.assertEqual(stored, record_payload(result))
        self.assertEqual(stored["metrics"][1]["label"], "정상")
        self.assertEqual(len(stored["metrics"][1]["grade_probabilities"]), 3)
        self.assertNotIn("preprocessing_version", stored["metrics"][1])

    def test_records_signatures_sessions_and_care_persist_across_app_restart(self):
        user = self.register().json["user"]
        result = self.analyze()
        self.assertEqual(self.save(result).status_code, 201)
        self.client.put("/api/care-checks", json={"date": "2026-11-01", "checks": ["observe"]})
        token = self.client.get_cookie(COOKIE_NAME).value
        restarted = create_app(DemoService(), database_path=self.database).test_client()
        restarted.set_cookie(COOKIE_NAME, token)
        self.assertEqual(restarted.get("/api/auth/me").json["user"], user)
        self.assertEqual(len(restarted.get("/api/records").json["records"]), 1)
        self.assertEqual(self.save(result, restarted).status_code, 200)
        self.assertEqual(restarted.get("/api/care-checks?date=2026-11-01").json["checks"], ["observe"])

    def test_other_account_cannot_read_save_or_delete_records_or_checks(self):
        self.register()
        result = self.analyze()
        self.save(result)
        self.client.put("/api/care-checks", json={"date": "2026-11-01", "checks": ["low-heat"]})
        other = self.app.test_client()
        self.register(nickname="other", client=other)
        self.assertEqual(other.get("/api/records").json["records"], [])
        self.assertEqual(self.save(result, other).status_code, 403)
        self.assertEqual(other.get("/api/care-checks?date=2026-11-01").json["checks"], [])
        self.assertEqual(other.delete("/api/records").json, {"deleted": 0})
        self.assertEqual(len(self.client.get("/api/records").json["records"]), 1)

    def test_tampered_or_guest_result_cannot_be_saved_to_account(self):
        guest_result = self.analyze()
        self.register()
        self.assertEqual(self.save(guest_result).status_code, 403)
        result = self.analyze()
        tampered = deepcopy(result)
        tampered["metrics"][0]["label"] = "fake grade"
        self.assertEqual(self.save(tampered).status_code, 403)
        result["save_token"] = "비정상 토큰"
        self.assertEqual(self.save(result).status_code, 403)
        malformed = self.client.post("/api/records", json={"record": {"metrics": 3}, "save_token": "fake"})
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(self.client.get("/api/records").json["records"], [])

    def test_care_checks_validate_date_ids_and_replace_for_own_day(self):
        self.register()
        valid = {"date": "2026-11-01", "checks": ["observe", "low-heat"]}
        self.assertEqual(self.client.put("/api/care-checks", json=valid).status_code, 200)
        self.assertEqual(self.client.get("/api/care-checks?date=2026-11-01").json["checks"], ["low-heat", "observe"])
        self.assertEqual(self.client.get("/api/care-checks?date=2026-11-02").json["checks"], [])
        for invalid in [
            {"date": "2026-02-30", "checks": []}, {"date": "20261101", "checks": []},
            {"date": "2026-11-01", "checks": None}, {"date": "2026-11-01", "checks": ["unknown"]},
            {"date": "2026-11-01", "checks": ["observe", "observe"]}, {"date": "2026-11-01", "checks": "observe"},
        ]:
            self.assertEqual(self.client.put("/api/care-checks", json=invalid).status_code, 400, invalid)
        self.assertEqual(self.client.put("/api/care-checks", json={"date": "2026-11-01", "checks": []}).json["checks"], [])

    def test_signatures_survive_browser_integer_float_roundtrip(self):
        self.register()
        result = self.analyze()
        result["elapsed_ms"] = 100.0
        result["metrics"][0]["probabilities"] = [1.0, 0.0, 0.0, 0.0]
        result["metrics"][0]["confidence"] = 1.0
        result["save_token"] = self.store.sign_result(result, self.client.get("/api/auth/me").json["user"]["id"])
        def browser_numeric_roundtrip(item):
            if isinstance(item, float) and item.is_integer():
                return int(item)
            if isinstance(item, list):
                return [browser_numeric_roundtrip(child) for child in item]
            if isinstance(item, dict):
                return {key: browser_numeric_roundtrip(child) for key, child in item.items()}
            return item
        browser_result = browser_numeric_roundtrip(json.loads(json.dumps(result)))
        self.assertEqual(self.save(browser_result).status_code, 201)

    def test_stale_tab_account_header_cannot_affect_the_new_account(self):
        old_user = self.register().json["user"]
        new_user = self.register(nickname="second").json["user"]
        result = self.analyze()
        self.save(result)
        self.client.put("/api/care-checks", json={"date": "2026-11-01", "checks": ["observe"]})
        stale_header = {"X-Scalp-Account": str(old_user["id"])}
        for response in [
            self.client.get("/api/records", headers=stale_header),
            self.client.delete("/api/records", headers=stale_header),
            self.client.post("/api/records", json={"record": record_payload(result), "save_token": result["save_token"]}, headers=stale_header),
            self.client.get("/api/care-checks?date=2026-11-01", headers=stale_header),
            self.client.put("/api/care-checks", json={"date": "2026-11-01", "checks": ["low-heat"]}, headers=stale_header),
            self.client.post("/api/analyze", data={}, headers=stale_header),
            self.client.post("/api/analyze", data={}, headers={"X-Scalp-Account": "guest"}),
        ]:
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json["code"], "account_changed")
        self.assertEqual(len(self.client.get("/api/records").json["records"]), 1)
        self.assertEqual(self.client.get("/api/care-checks?date=2026-11-01").json["checks"], ["observe"])
        self.assertEqual(self.client.get("/api/records", headers={"X-Scalp-Account": str(new_user["id"])}).status_code, 200)
        self.client.post("/api/auth/logout", json={})
        self.assertEqual(self.client.get("/api/records", headers=stale_header).status_code, 409)
        self.assertEqual(self.client.post("/api/analyze", data={}, headers={"X-Scalp-Account": "guest"}).status_code, 400)

    def test_signup_gender_requires_consent_and_remains_optional(self):
        guest = self.client.get("/api/auth/me")
        self.assertIsNone(guest.json["user"])
        response = self.client.post("/api/auth/register", json={"nickname": "male-user", "password": "new-only-password", "gender": "male", "gender_consent": True})
        self.assertEqual(response.status_code, 201, response.json)
        user = response.json["user"]
        self.assertEqual(user["gender"], "male")
        self.assertIs(user["gender_consent"], True)
        self.assertEqual(user["profile_version"], 0)
        self.assertNotIn("password", user)
        with self.store.connection() as db:
            row = db.execute("SELECT gender_consented_at,gender_consent_version FROM users WHERE id=?", (user["id"],)).fetchone()
        self.assertIsInstance(row["gender_consented_at"], int)
        self.assertEqual(row["gender_consent_version"], "2026-11-03")
        for fields in ({"gender": "female"}, {"gender": "unknown", "gender_consent": True},
                       {"gender": "female", "gender_consent": "true"}, {"gender_consent": True}):
            invalid = self.client.post("/api/auth/register", json={"nickname": "rejected", "password": "fresh-password", **fields})
            self.assertEqual(invalid.status_code, 400, invalid.json)
        optional = self.register(nickname="no-gender").json["user"]
        self.assertIsNone(optional["gender"])
        self.assertIs(optional["gender_consent"], False)

    def test_profile_update_rotates_sessions_preserves_records_and_revokes_old_proof(self):
        user = self.register().json["user"]
        result = self.analyze()
        self.save(result)
        self.client.put("/api/care-checks", json={"date": "2026-11-01", "checks": ["observe"]})
        other_session = self.app.test_client()
        other_session.post("/api/auth/login", json={"nickname": "tester", "password": "246810"})
        previous_token = self.client.get_cookie(COOKIE_NAME).value
        response = self.client.patch("/api/auth/profile", json={"current_password": "246810", "nickname": "changed-user", "new_password": "new-login-only", "gender": "female", "gender_consent": True})
        self.assertEqual(response.status_code, 200, response.json)
        changed = response.json["user"]
        self.assertEqual(changed["id"], user["id"])
        self.assertEqual(changed["nickname"], "changed-user")
        self.assertEqual(changed["gender"], "female")
        self.assertEqual(changed["profile_version"], 1)
        self.assertEqual(changed["result_epoch"], user["result_epoch"] + 1)
        self.assertNotEqual(self.client.get_cookie(COOKIE_NAME).value, previous_token)
        self.assertEqual(self.client.get("/api/auth/me").json["user"], changed)
        self.assertIsNone(other_session.get("/api/auth/me").json["user"])
        self.assertEqual(len(self.client.get("/api/records").json["records"]), 1)
        self.assertEqual(self.client.get("/api/care-checks?date=2026-11-01").json["checks"], ["observe"])
        self.assertEqual(self.save(result).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/login", json={"nickname": "tester", "password": "246810"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"nickname": "changed-user", "password": "new-login-only"}).status_code, 200)
        stale = self.client.get("/api/care-checks?month=2026-11", headers={"X-Scalp-Profile-Version": "0"})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json["code"], "profile_changed")

    def test_profile_mutation_requires_current_password_and_cannot_target_other_user(self):
        user = self.register().json["user"]
        other = self.app.test_client()
        second = self.register(nickname="second", client=other).json["user"]
        for fields in ({}, {"current_password": "wrong"}, {"current_password": "246810", "new_password": ""}):
            response = self.client.patch("/api/auth/profile", json={"nickname": "changed", **fields})
            self.assertIn(response.status_code, (400, 403))
        duplicate = self.client.patch("/api/auth/profile", json={"current_password": "246810", "nickname": "SECOND"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.client.get("/api/auth/me").json["user"], user)
        response = self.client.patch("/api/auth/profile", json={"current_password": "246810", "user_id": second["id"], "role": "admin", "nickname": "new-own-name"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["id"], user["id"])
        self.assertEqual(response.json["user"]["role"], "user")
        self.assertEqual(other.get("/api/auth/me").json["user"], second)
        self.assertEqual(self.client.patch("/api/auth/profile", json={"current_password": "246810"}, headers={"Origin": "https://foreign.example"}).status_code, 403)
        self.assertEqual(self.client.patch("/api/auth/profile", data="raw").status_code, 415)

    def test_profile_consent_withdrawal_removes_gender_and_consent_metadata(self):
        response = self.client.post("/api/auth/register", json={"nickname": "consent-user", "password": "own-password", "gender": "male", "gender_consent": True})
        user_id = response.json["user"]["id"]
        response = self.client.patch("/api/auth/profile", json={"current_password": "own-password", "gender_consent": False})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIsNone(response.json["user"]["gender"])
        self.assertIs(response.json["user"]["gender_consent"], False)
        with self.store.connection() as db:
            row = db.execute("SELECT gender,gender_consent,gender_consented_at,gender_consent_version FROM users WHERE id=?", (user_id,)).fetchone()
        self.assertEqual(tuple(row), (None, 0, None, None))

    def test_care_month_is_sorted_owner_scoped_and_future_writes_are_rejected(self):
        self.register()
        self.client.put("/api/care-checks", json={"date": "2026-11-02", "checks": ["low-heat"]})
        self.client.put("/api/care-checks", json={"date": "2026-10-31", "checks": ["gentle-wash"]})
        self.client.put("/api/care-checks", json={"date": "2026-11-01", "checks": []})
        response = self.client.get("/api/care-checks?month=2026-11")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"month": "2026-11", "days": [{"date": "2026-11-01", "checks": []}, {"date": "2026-11-02", "checks": ["low-heat"]}]})
        other = self.app.test_client()
        self.register(nickname="other", client=other)
        self.assertEqual(other.get("/api/care-checks?month=2026-11").json["days"], [])
        for query in ("2026-1", "2026-13", "abcd", "2026-11&date=2026-11-01"):
            self.assertEqual(self.client.get("/api/care-checks?month=" + query).status_code, 400)
        self.assertEqual(self.client.put("/api/care-checks", json={"date": "9999-01-01", "checks": ["observe"]}).status_code, 400)
        self.assertEqual(self.client.get("/api/care-checks?date=9999-01-01").json["checks"], [])

    def test_json_and_same_origin_mutation_boundaries(self):
        self.assertEqual(self.client.post("/api/auth/register", data={"nickname": "test", "password": "1"}).status_code, 415)
        self.assertEqual(self.register(nickname="").status_code, 400)
        self.assertEqual(self.register(password="").status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register", json=[]).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/register", json={"nickname": "test", "password": "1"}, headers={"Origin": "https://other.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/register", json={"nickname": "test", "password": "1"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.register()
        self.assertEqual(self.client.delete("/api/records", headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/logout", data="").status_code, 415)


if __name__ == "__main__":
    unittest.main()