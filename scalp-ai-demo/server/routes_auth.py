"""회원가입, 로그인, 로그아웃.

POST /api/auth/signup   아이디·이름·성별·비밀번호·개인정보 동의 → 가입과 동시에 로그인
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me       로그인한 회원 정보 (로그인 전이면 401)
"""
from __future__ import annotations

import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

import auth
import db

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 개인정보 안내 문구를 바꾸면 이 값도 바꿔서, 어떤 안내에 동의했는지 남긴다
CONSENT_VERSION = "2026-11"
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")


class SignupIn(BaseModel):
    username: str = Field(max_length=20)
    name: str = Field(min_length=1, max_length=20)
    gender: Literal["female", "male"]
    password: str = Field(min_length=8, max_length=128)
    consent: bool       # 개인정보(가입 정보, 분석 결과, 루틴 기록) 수집·이용 동의


class LoginIn(BaseModel):
    username: str = Field(max_length=20)
    password: str = Field(max_length=128)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    gender: Literal["female", "male"]

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("이름을 입력해 주세요.")
        return value.strip()


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    confirmation: Literal["탈퇴"]


def user_json(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "username": row["username"], "name": row["name"], "gender": row["gender"],
            "role": row["role"], "since": row["created_at"][:10]}


@router.post("/signup", status_code=201)
def signup(body: SignupIn, response: Response, conn: sqlite3.Connection = Depends(db.get_db)):
    username = body.username.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "아이디는 영문 소문자, 숫자, 밑줄로 3~20자여야 해요.")
    if not body.consent:
        raise HTTPException(400, "개인정보 수집·이용에 동의해야 가입할 수 있어요.")
    now = db.iso(db.now_kst())
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users (username, name, gender, password_hash, consent_version, consented_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, body.name.strip(), body.gender, auth.hash_password(body.password),
                 CONSENT_VERSION, now, now))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "이미 사용 중인 아이디예요.")
    auth.start_session(conn, response, cur.lastrowid)
    return user_json(conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.post("/login")
def login(body: LoginIn, response: Response, conn: sqlite3.Connection = Depends(db.get_db)):
    row = auth.check_login(conn, body.username.strip().lower(), body.password)
    if not row:
        raise HTTPException(401, "아이디 또는 비밀번호를 확인해 주세요.")
    auth.start_session(conn, response, row["id"])
    return user_json(row)


@router.post("/logout", status_code=204)
def logout(response: Response, scalp_session: str | None = Cookie(default=None),
           conn: sqlite3.Connection = Depends(db.get_db)):
    auth.end_session(conn, response, scalp_session)


@router.get("/me")
def me(user: sqlite3.Row = Depends(auth.current_user)):
    return user_json(user)


@router.patch("/me")
def update_profile(body: ProfileIn, user: sqlite3.Row = Depends(auth.current_user),
                   conn: sqlite3.Connection = Depends(db.get_db)):
    with conn:
        conn.execute("UPDATE users SET name = ?, gender = ? WHERE id = ?",
                     (body.name, body.gender, user["id"]))
    return user_json(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())


@router.put("/password", status_code=204)
def change_password(body: PasswordIn, response: Response,
                    user: sqlite3.Row = Depends(auth.current_user),
                    conn: sqlite3.Connection = Depends(db.get_db)):
    if not auth.verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(400, "현재 비밀번호를 확인해 주세요.")
    if body.current_password == body.new_password:
        raise HTTPException(400, "새 비밀번호는 현재 비밀번호와 다르게 입력해 주세요.")
    with conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (auth.hash_password(body.new_password), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    auth.start_session(conn, response, user["id"])


@router.delete("/me", status_code=204)
def delete_account(body: DeleteAccountIn, response: Response,
                   user: sqlite3.Row = Depends(auth.current_user),
                   conn: sqlite3.Connection = Depends(db.get_db)):
    if not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(400, "비밀번호를 확인해 주세요.")
    if user["username"] in ("admin", "demo"):
        raise HTTPException(403, "기본 시연 계정은 탈퇴할 수 없어요.")
    with conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
