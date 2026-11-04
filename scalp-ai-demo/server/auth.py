"""비밀번호 해시와 로그인 세션.

세션은 무작위 토큰을 HttpOnly 쿠키로 주고, DB에는 토큰의 해시만 저장한다.
비밀번호는 PBKDF2-SHA256으로 해시한다(표준 라이브러리만 사용).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import timedelta

from fastapi import Cookie, Depends, HTTPException, Response

import db

SESSION_COOKIE = "scalp_session"
SESSION_DAYS = 7
PBKDF2_ROUNDS = 240_000
SECURE_COOKIE = os.environ.get("SCALP_COOKIE_SECURE") == "1"   # https로 배포할 때 켠다


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


# 없는 아이디로 로그인할 때도 같은 시간이 걸리게 하려고 쓰는 가짜 해시
_DUMMY_HASH = hash_password("not-a-real-password")


def check_login(conn: sqlite3.Connection, username: str, password: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
    return row if row and ok else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(conn: sqlite3.Connection, response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    now = db.now_kst()
    with conn:
        conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                     (_token_hash(token), user_id, db.iso(now), db.iso(now + timedelta(days=SESSION_DAYS))))
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=SECURE_COOKIE, path="/")


def end_session(conn: sqlite3.Connection, response: Response, token: str | None) -> None:
    if token:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_user(scalp_session: str | None = Cookie(default=None),
                 conn: sqlite3.Connection = Depends(db.get_db)) -> sqlite3.Row:
    """로그인한 회원을 돌려준다. 세션이 없거나 만료됐으면 401."""
    if scalp_session:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (_token_hash(scalp_session), db.iso(db.now_kst()))).fetchone()
        if row:
            return row
    raise HTTPException(401, "로그인이 필요해요.")
