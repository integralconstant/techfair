"""Run: python -m unittest test_account (from server/). Uses an isolated in-memory DB."""
import sqlite3
import unittest

from fastapi import HTTPException, Response
from pydantic import ValidationError

import auth
import db
import routes_auth as routes


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(db.SCHEMA)
        for username in ("alice", "bob"):
            routes.signup(routes.SignupIn(username=username, name=username, gender="female",
                          password="original123", consent=True), Response(), self.conn)
        self.user = self.conn.execute("SELECT * FROM users WHERE username='alice'").fetchone()

    def tearDown(self):
        self.conn.close()

    def test_profile_changes_only_authenticated_user(self):
        result = routes.update_profile(routes.ProfileIn(name=" Alice ", gender="male"), self.user, self.conn)
        self.assertEqual(result["name"], "Alice")
        self.assertNotIn("password_hash", result)
        self.assertEqual(self.conn.execute("SELECT name FROM users WHERE username='bob'").fetchone()[0], "bob")
        with self.assertRaises(ValidationError):
            routes.ProfileIn(name="   ", gender="female")

    def test_password_change_revokes_sessions(self):
        with self.assertRaises(HTTPException):
            routes.change_password(routes.PasswordIn(current_password="wrong", new_password="changed123"),
                                   Response(), self.user, self.conn)
        token_hash = self.conn.execute("SELECT token_hash FROM sessions WHERE user_id=?", (self.user["id"],)).fetchone()[0]
        routes.change_password(routes.PasswordIn(current_password="original123", new_password="changed123"),
                               Response(), self.user, self.conn)
        self.assertIsNone(auth.check_login(self.conn, "alice", "original123"))
        self.assertIsNotNone(auth.check_login(self.conn, "alice", "changed123"))
        self.assertIsNone(self.conn.execute("SELECT * FROM sessions WHERE token_hash=?", (token_hash,)).fetchone())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (self.user["id"],)).fetchone()[0], 1)

    def test_delete_cascades_only_own_data(self):
        uid = self.user["id"]
        with self.conn:
            self.conn.execute("INSERT INTO analyses(user_id,analyzed_on,dandruff,sebum,hairloss,erythema,created_at) VALUES (?, '2026-01-01',0,0,0,0,'now')", (uid,))
            self.conn.execute("INSERT INTO daily_mission_log VALUES (?, '2026-01-01','test',NULL)", (uid,))
            self.conn.execute("INSERT INTO weekly_mission_log VALUES (?, '2026-01-01','test',1)", (uid,))
        with self.assertRaises(HTTPException):
            routes.delete_account(routes.DeleteAccountIn(password="wrong", confirmation="탈퇴"), Response(), self.user, self.conn)
        routes.delete_account(routes.DeleteAccountIn(password="original123", confirmation="탈퇴"), Response(), self.user, self.conn)
        for table in ("sessions", "analyses", "daily_mission_log", "weekly_mission_log"):
            self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (uid,)).fetchone()[0], 0)
        self.assertIsNotNone(auth.check_login(self.conn, "bob", "original123"))

    def test_anonymous_is_rejected(self):
        with self.assertRaises(HTTPException) as exc:
            auth.current_user(None, self.conn)
        self.assertEqual(exc.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
