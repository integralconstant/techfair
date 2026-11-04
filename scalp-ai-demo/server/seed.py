"""시드 계정과 더미 데이터.

서버가 켜질 때 계정이 없으면 자동으로 만든다. 더미 기록은 이 두 계정에만 들어간다(새로 가입한 회원은 빈 기록으로 시작).
    admin   어드민. 화면에서 게스트/회원 보기, 남성/여성, 결과 직접 지정을 바꿀 수 있다
    demo    일반 회원. 그래프와 미션을 보여 주는 계정

    python seed.py            계정이 없을 때만 만든다
    python seed.py --reset    두 계정과 그 기록을 지우고 오늘 기준으로 다시 만든다

어드민 비밀번호는 환경변수 SCALP_ADMIN_PASSWORD로 바꿀 수 있다.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import auth
import db
from routes_auth import CONSENT_VERSION

ADMIN_PASSWORD = os.environ.get("SCALP_ADMIN_PASSWORD") or "12345"
# (아이디, 비밀번호, 이름, 성별, 역할)
ACCOUNTS = [
    ("admin", ADMIN_PASSWORD, "관리자", "female", "admin"),
    ("demo", "demo1234", "시연 회원", "female", "member"),
]

DAYS = 56                           # 오늘 기준 과거 8주 (어제까지)
EARLY = 24                          # 앞쪽 24일은 염증 미션도 뜨던 시기

# 화면의 WEEKLY_MISSIONS(care-data.js)와 같은 목표 횟수
WEEKLY_GOALS = {"w_rescan": 1, "w_dandruff_shampoo": 2, "w_no_styling": 3, "w_no_heat": 5, "w_flare_review": 1}
WEEKLY_ORDER = ["w_rescan", "w_dandruff_shampoo", "w_no_styling", "w_no_heat", "w_flare_review"]
EXAMPLE_RECORDS = Path(__file__).resolve().parent / "seed_data" / "example_records.json"


def _round_half_up(x: float) -> int:        # JS Math.round와 같게 맞춘다 (파이썬 round는 짝수로 반올림)
    return math.floor(x + 0.5)


def mission_examples(t: date) -> tuple[dict[date, tuple[list[str], list[str]]], dict[date, dict[str, int]]]:
    """오늘 t 기준 과거 56일의 일 루틴(shown, done)과 지난 주들의 주 루틴 횟수를 규칙으로 만든다."""
    daily: dict[date, tuple[list[str], list[str]]] = {}
    for i in range(DAYS):
        shown = ["c_rinse", "c_dry", "d_lather", "h_loose"] + (["e_nofrag"] if i < EARLY else [])
        rate = 0.35 + 0.55 * i / (DAYS - 1)
        skipped = i < DAYS - 10 and (i * 7 + 3) % 9 == 0
        done = [] if skipped else [m for k, m in enumerate(shown) if ((i * 37 + k * 61 + 11) % 100) / 100 < rate]
        if not skipped and not done:
            done.append(shown[0])
        daily[t + timedelta(days=i - DAYS)] = (shown, done)

    # 주 루틴은 지난 주까지만. 이번 주는 직접 채운다
    this_week = db.monday_of(t)
    starts = sorted({db.monday_of(d) for d in daily if db.monday_of(d) < this_week})
    weekly: dict[date, dict[str, int]] = {}
    for w, start in enumerate(starts):
        rate = 0.3 + 0.65 * w / max(1, len(starts) - 1)
        ids = [m for m in WEEKLY_ORDER
               if m in ("w_rescan", "w_dandruff_shampoo", "w_no_styling", "w_no_heat")
               or (m == "w_flare_review" and start < t - timedelta(days=32))]
        weekly[start] = {m: max(0, min(WEEKLY_GOALS[m], _round_half_up(WEEKLY_GOALS[m] * (rate - 0.2 * (k % 2)))))
                         for k, m in enumerate(ids)}
    return daily, weekly


def seed_account(conn: sqlite3.Connection, account: tuple, t: date | None = None) -> int:
    """계정 하나와 더미 기록을 만들고 user id를 돌려준다. 이미 있으면 지우고 다시 만든다."""
    username, password, name, gender, role = account
    t = t or db.today()
    records = json.loads(EXAMPLE_RECORDS.read_text(encoding="utf-8"))
    daily, weekly = mission_examples(t)
    created = records[0]["date"] + "T09:00:00+09:00"      # 첫 기록일에 가입한 회원처럼 보이게 한다
    with conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))     # 하위 기록은 CASCADE로 함께 지워진다
        uid = conn.execute(
            "INSERT INTO users (username, name, gender, role, password_hash, consent_version, consented_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (username, name, gender, role, auth.hash_password(password), CONSENT_VERSION, created, created)).lastrowid
        conn.executemany(
            "INSERT INTO analyses (user_id, analyzed_on, dandruff, sebum, hairloss, erythema, is_example, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            [(uid, r["date"], *r["grades"], r["date"] + "T09:00:00+09:00") for r in records])
        conn.executemany(
            "INSERT INTO daily_mission_log (user_id, log_date, mission_id, done_at) VALUES (?, ?, ?, ?)",
            [(uid, d.isoformat(), m, f"{d.isoformat()}T21:00:00+09:00" if m in done else None)
             for d, (shown, done) in daily.items() for m in shown])
        conn.executemany(
            "INSERT INTO weekly_mission_log (user_id, week_start, mission_id, count) VALUES (?, ?, ?, ?)",
            [(uid, start.isoformat(), m, n) for start, counts in weekly.items() for m, n in counts.items()])
    return uid


def ensure_accounts(conn: sqlite3.Connection) -> None:
    for account in ACCOUNTS:
        if not conn.execute("SELECT 1 FROM users WHERE username = ?", (account[0],)).fetchone():
            seed_account(conn, account)


if __name__ == "__main__":
    db.init()
    connection = db.connect()
    try:
        if "--reset" in sys.argv:
            for account in ACCOUNTS:
                seed_account(connection, account)
            print("시드 계정을 오늘 기준으로 다시 만들었어요.")
        else:
            ensure_accounts(connection)
        print("계정: " + ", ".join(f"{a[0]} / {a[1]}" for a in ACCOUNTS))
    finally:
        connection.close()
