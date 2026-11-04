"""Verify admin authorization, preserved migrations and targeted operations."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash

from accounts import AccountStore, COOKIE_NAME, record_payload
from server import create_app
from test_accounts import DemoService

ROOT = Path(__file__).resolve().parents[1]


class AdminService(DemoService):
    error = None

    def health(self):
        return {"status": "ready", "configuration_id": "unit-config", "models": [
            {"id": name, "name": name, "ready": True, "num_classes": 4 if i == 0 else 3,
             "grade_labels": ["무", "유"] if i == 1 else ["정상", "경증", "중증"],
             "settings_verified": i in (0, 1)}
            for i, name in enumerate(("flakes", "sebum", "hair_loss", "erythema"))]}


class AdminApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "admin.sqlite3"
        self.service = AdminService()
        self.app = create_app(self.service, database_path=self.database)
        self.app.config["TESTING"] = True
        self.store = self.app.extensions["account_store"]
        self.admin_user = self.store.create_admin("operator", "operator-test-secret")
        self.admin = self.app.test_client()
        response = self.admin.post("/api/auth/login", json={"nickname": "operator", "password": "operator-test-secret"})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["user"]["role"], "admin")

    def member(self, nickname=None, password="123456"):
        if nickname is None:
            with self.store.connection() as db:
                nickname = f"member-{db.execute('SELECT COUNT(*) FROM users').fetchone()[0]}"
        client = self.app.test_client()
        response = client.post("/api/auth/register", json={"nickname": nickname, "password": password})
        self.assertEqual(response.status_code, 201, response.json)
        return client, response.json["user"]

    def analysis(self, client):
        stream = io.BytesIO()
        with Image.new("RGB", (8, 6), (40, 60, 80)) as image:
            image.save(stream, format="PNG")
        stream.seek(0)
        response = client.post("/api/analyze", data={"photos": (stream, "test-private-photo.png")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def save(self, client, result, headers=None):
        return client.post("/api/records", json={"record": record_payload(result), "save_token": result["save_token"]}, headers=headers)

    def seed(self, client):
        result = self.analysis(client)
        self.assertEqual(self.save(client, result).status_code, 201)
        self.assertEqual(client.put("/api/care-checks", json={"date": result["date"], "checks": ["observe"]}).status_code, 200)
        return result

    def test_guest_and_member_cannot_use_any_admin_endpoint(self):
        client, user = self.member()
        guest = self.app.test_client()
        paths = [("get", "/api/admin/overview", None), ("get", "/api/admin/users", None),
                 ("get", "/api/admin/actions", None),
                 ("post", f"/api/admin/users/{user['id']}/reset-password", {}),
                 ("post", f"/api/admin/users/{user['id']}/clear-data", {"confirm_user_id": user["id"]}),
                 ("delete", f"/api/admin/users/{user['id']}", {"confirm_user_id": user["id"]})]
        for method, path, body in paths:
            for actor, expected in ((guest, 401), (client, 403)):
                response = getattr(actor, method)(path, **({"json": body} if body is not None else {}))
                self.assertEqual(response.status_code, expected, (method, path, response.json))
        forged = client.get("/api/admin/users", headers={"X-Role": "admin", "X-Admin": "true"})
        self.assertEqual(forged.status_code, 403)

    def test_signup_payload_cannot_grant_admin_role(self):
        client = self.app.test_client()
        response = client.post("/api/auth/register", json={"nickname": "forged", "password": "1", "role": "admin", "result_epoch": 999})
        if response.status_code == 201:
            self.assertEqual(response.json["user"]["role"], "user")
            self.assertEqual(response.json["user"]["result_epoch"], 0)
        else:
            self.assertIn(response.status_code, (400, 403))
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0], 1)

    def test_overview_and_member_rows_expose_counts_not_credentials_or_records(self):
        client, user = self.member()
        self.seed(client)
        response = self.admin.get("/api/admin/overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["counts"]["accounts"], 2)
        self.assertEqual(response.json["counts"]["members"], 1)
        self.assertEqual(response.json["counts"]["admins"], 1)
        self.assertEqual(response.json["counts"]["records"], 1)
        self.assertEqual(response.json["counts"]["care_days"], 1)
        self.assertEqual(len(response.json["health"]["models"]), 4)
        rows = self.admin.get("/api/admin/users").json["users"]
        row = next(item for item in rows if item["id"] == user["id"])
        self.assertEqual(row["record_count"], 1)
        self.assertEqual(row["care_days"], 1)
        self.assertEqual(row["nickname"], user["nickname"])
        self.assertIsInstance(row["created_at"], int)
        encoded = json.dumps({"overview": response.json, "users": rows})
        for forbidden in ("password_hash", "save_token", "probabilities", "test-private-photo"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_admin_permission_is_refreshed_from_database_on_every_request(self):
        with self.store.connection() as db:
            db.execute("UPDATE users SET role='user' WHERE id=?", (self.admin_user["id"],))
        response = self.admin.get("/api/admin/users")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.admin.get("/api/auth/me").json["user"]["role"], "user")

    def test_reset_password_targets_id_revokes_all_sessions_and_old_proof(self):
        first, target = self.member(password="111111")
        other, sibling = self.member(password="222222")
        result = self.seed(first)
        second_session = self.app.test_client()
        second_session.post("/api/auth/login", json={"nickname": target["nickname"], "password": "111111"})
        response = self.admin.post(f"/api/admin/users/{target['id']}/reset-password", json={})
        self.assertEqual(response.status_code, 200, response.json)
        password = response.json["temporary_password"]
        self.assertTrue(password.isdigit() and len(password) == 8)
        self.assertGreaterEqual(response.json["revoked_sessions"], 2)
        self.assertIsNone(first.get("/api/auth/me").json["user"])
        self.assertIsNone(second_session.get("/api/auth/me").json["user"])
        self.assertEqual(first.post("/api/auth/login", json={"nickname": target["nickname"], "password": "111111"}).status_code, 401)
        login = first.post("/api/auth/login", json={"nickname": target["nickname"], "password": password})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json["user"]["id"], target["id"])
        self.assertEqual(login.json["user"]["result_epoch"], target["result_epoch"] + 1)
        self.assertEqual(len(first.get("/api/records").json["records"]), 1)
        self.assertEqual(self.save(first, result).status_code, 403)
        self.assertEqual(other.get("/api/auth/me").json["user"]["id"], sibling["id"])
        self.assertEqual(other.post("/api/auth/login", json={"nickname": sibling["nickname"], "password": "222222"}).status_code, 200)
        with self.store.connection() as db:
            stored = db.execute("SELECT password_hash FROM users WHERE id=?", (target["id"],)).fetchone()[0]
        self.assertNotEqual(stored, password)
        self.assertTrue(check_password_hash(stored, password))
        encoded = json.dumps(self.admin.get("/api/admin/actions").json)
        self.assertNotIn(password, encoded)
        self.assertNotIn(stored, encoded)

    def test_generated_reset_pin_differs_from_target_and_duplicate_nickname_peer(self):
        _, target = self.member(password="87654321")
        other, sibling = self.member(password="12345678")
        # Legacy duplicate fixtures bypass the new public signup rejection.
        with self.store.connection() as db:
            db.execute("UPDATE users SET nickname=?,nickname_key=? WHERE id=?",
                       (target["nickname"], self.store.nickname_key(target["nickname"]), sibling["id"]))
        sibling["nickname"] = target["nickname"]
        with patch("accounts.secrets.randbelow", side_effect=[12345678, 87654321, 11112222]):
            response = self.admin.post(f"/api/admin/users/{target['id']}/reset-password", json={})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["temporary_password"], "11112222")
        logged_in = other.post("/api/auth/login", json={"nickname": sibling["nickname"], "password": "12345678"})
        self.assertEqual(logged_in.json["user"]["id"], sibling["id"])

    def test_clear_data_only_affects_target_and_rejects_stale_epoch_and_proof(self):
        first, target = self.member(password="111111")
        other, sibling = self.member(password="222222")
        original = self.seed(first)
        self.seed(other)
        response = self.admin.post(f"/api/admin/users/{target['id']}/clear-data", json={"confirm_user_id": target["id"]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["deleted_records"], 1)
        self.assertEqual(response.json["deleted_care_days"], 1)
        self.assertEqual(first.get("/api/records").json["records"], [])
        self.assertEqual(first.get("/api/care-checks?date=" + original["date"]).json["checks"], [])
        self.assertEqual(len(other.get("/api/records").json["records"]), 1)
        self.assertEqual(self.save(first, original).status_code, 403)
        headers = {"X-Scalp-Account": str(target["id"]), "X-Scalp-Result-Epoch": str(target["result_epoch"])}
        response = first.put("/api/care-checks", json={"date": original["date"], "checks": ["observe"]}, headers=headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["code"], "data_changed")
        current = first.get("/api/auth/me").json["user"]
        self.assertEqual(current["result_epoch"], target["result_epoch"] + 1)
        fresh = self.analysis(first)
        self.assertEqual(self.save(first, fresh).status_code, 201)
        self.assertEqual(other.get("/api/auth/me").json["user"]["id"], sibling["id"])

    def test_clear_and_delete_require_matching_confirmation_id(self):
        client, user = self.member()
        self.seed(client)
        for method, path in (("post", f"/api/admin/users/{user['id']}/clear-data"), ("delete", f"/api/admin/users/{user['id']}")):
            response = getattr(self.admin, method)(path, json={"confirm_user_id": user["id"] + 1})
            self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(len(client.get("/api/records").json["records"]), 1)

    def test_delete_cascades_only_target_and_audit_keeps_identity_snapshot(self):
        first, target = self.member(password="111111")
        other, sibling = self.member(password="222222")
        self.seed(first)
        self.seed(other)
        response = self.admin.delete(f"/api/admin/users/{target['id']}", json={"confirm_user_id": target["id"]})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["deleted_user_id"], target["id"])
        self.assertEqual(response.json["deleted_records"], 1)
        self.assertEqual(response.json["deleted_care_days"], 1)
        self.assertIsNone(first.get("/api/auth/me").json["user"])
        with self.store.connection() as db:
            for table in ("sessions", "records", "care_checks"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (target["id"],)).fetchone()[0], 0)
        self.assertEqual(len(other.get("/api/records").json["records"]), 1)
        self.assertEqual(other.get("/api/auth/me").json["user"]["id"], sibling["id"])
        actions = self.admin.get("/api/admin/actions").json["actions"]
        deletion = next(item for item in actions if item["action"] == "user_deleted")
        self.assertEqual(deletion["target_id"], target["id"])
        self.assertEqual(deletion["target_nickname"], target["nickname"])
        self.assertEqual(deletion["actor_id"], self.admin_user["id"])
        self.assertNotIn("password", json.dumps(deletion["details"]))

    def test_admin_accounts_are_read_only_targets_and_missing_target_is_404(self):
        for target in (self.admin_user, self.store.create_admin("second-operator", "another-test-secret")):
            for method, suffix, body in (("post", "/reset-password", {}), ("post", "/clear-data", {"confirm_user_id": target["id"]}), ("delete", "", {"confirm_user_id": target["id"]})):
                response = getattr(self.admin, method)(f"/api/admin/users/{target['id']}" + suffix, json=body)
                self.assertEqual(response.status_code, 403, response.json)
        response = self.admin.post("/api/admin/users/999999/reset-password", json={})
        self.assertEqual(response.status_code, 404)

    def test_admin_mutations_enforce_json_and_origin(self):
        _, target = self.member()
        path = f"/api/admin/users/{target['id']}/reset-password"
        self.assertEqual(self.admin.post(path, data={}).status_code, 415)
        self.assertEqual(self.admin.post(path, json={}, headers={"Origin": "https://foreign.example"}).status_code, 403)
        self.assertEqual(self.admin.get("/api/admin/users", headers={"X-Scalp-Account": "guest"}).status_code, 409)

    def test_explicit_old_request_epoch_cannot_sign_a_fresh_valid_result_after_reset(self):
        client, user = self.member()
        result = self.analysis(client)
        snapshot = user["result_epoch"]
        self.admin.post(f"/api/admin/users/{user['id']}/clear-data", json={"confirm_user_id": user["id"]})
        result["save_token"] = self.store.sign_result(result, user["id"], result_epoch=snapshot)
        self.assertEqual(self.save(client, result).status_code, 403)


class AdminMigrationTests(unittest.TestCase):
    def test_old_database_migrates_idempotently_without_changing_existing_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite3"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,nickname TEXT NOT NULL,password_hash TEXT NOT NULL,created_at INTEGER NOT NULL)")
            hashed = generate_password_hash("old-demo-password")
            db.execute("INSERT INTO users(id,nickname,password_hash,created_at) VALUES(41,?,?,100)", ("legacy", hashed))
            db.commit()
            db.close()
            first = AccountStore(path)
            with first.connection() as db:
                db.execute("INSERT INTO records(user_id,record_id,record_date,payload) VALUES(41,'original','2026-11-01',?)", ('{"raw":"unchanged"}',))
                db.execute("INSERT INTO care_checks(user_id,check_date,checks) VALUES(41,?,?)", ("2026-11-01", json.dumps(["observe"])))
            token = first.new_session(41)
            before = first.records(41)
            second = AccountStore(path)
            user = second.current_user(token)
            self.assertEqual(user["id"], 41)
            self.assertEqual(user["role"], "user")
            self.assertEqual(user["result_epoch"], 0)
            self.assertEqual(second.records(41), before)
            self.assertEqual(second.care_checks(41, "2026-11-01")["checks"], ["observe"])
            with second.connection() as db:
                self.assertEqual(db.execute("SELECT password_hash FROM users WHERE id=41").fetchone()[0], hashed)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0], 0)

    def test_cli_updates_existing_admin_without_printing_password_or_changing_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "cli-update.sqlite3"
            store = AccountStore(database)
            admin = store.create_admin("original-admin", "original-secret")
            session = store.new_session(admin["id"])
            with store.connection() as db:
                db.execute("INSERT INTO care_checks(user_id,check_date,checks) VALUES(?,?,?)", (admin["id"], "2026-11-01", '["observe"]'))
            password = "isolated-new-secret"
            completed = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/manage_admin.py"), "--database", str(database),
                                        "update", "--user-id", str(admin["id"]), "--nickname", "updated-admin", "--password-stdin"],
                                       input=password + "\n", cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            user = json.loads(completed.stdout)["user"]
            self.assertEqual(user["id"], admin["id"])
            self.assertEqual(user["nickname"], "updated-admin")
            self.assertEqual(user["role"], "admin")
            self.assertNotIn(password, completed.stdout + completed.stderr)
            self.assertIsNone(store.current_user(session))
            self.assertEqual(store.login({"nickname": "updated-admin", "password": password})["id"], admin["id"])
            self.assertEqual(store.care_checks(admin["id"], "2026-11-01")["checks"], ["observe"])
            actions = store.admin_actions(admin["id"])
            self.assertTrue(any(action["action"] == "admin_credentials_updated" for action in actions))
            self.assertNotIn(password, json.dumps(actions))

    def test_cli_creates_admin_only_in_explicit_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "cli.sqlite3"
            env = {**os.environ, "PYTHONUTF8": "1"}
            completed = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "manage_admin.py"),
                                        "--database", str(database), "create", "--nickname", "cli-operator", "--generate-password"],
                                       cwd=ROOT, env=env, text=True, encoding="utf-8", capture_output=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            # Read only the isolated database; no production credentials are used.
            store = AccountStore(database)
            with store.connection() as db:
                row = db.execute("SELECT id,role,password_hash FROM users WHERE nickname='cli-operator'").fetchone()
            self.assertEqual(row["role"], "admin")
            self.assertNotIn(row["password_hash"], completed.stdout)
            output = json.loads(completed.stdout)
            self.assertEqual(output["user"]["id"], row["id"])
            self.assertEqual(output["user"]["role"], "admin")
            self.assertTrue(check_password_hash(row["password_hash"], output["temporary_password"]))


if __name__ == "__main__":
    unittest.main()
