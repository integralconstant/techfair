"""SQLite 저장소와 날짜 도구.

DB 파일은 server/data/scalp.db (환경변수 SCALP_DB로 바꿀 수 있다). 서버가 켜질 때 init()이 테이블을 만든다.
시연용이라 서버가 따로 필요 없는 SQLite를 쓴다. 다른 DB로 옮길 때는 이 파일의 SCHEMA와 connect()만 바꾸면 된다.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

KST = timezone(timedelta(hours=9))      # 한국은 서머타임이 없어서 고정 오프셋이면 된다
DB_PATH = Path(os.environ.get("SCALP_DB") or Path(__file__).resolve().parent / "data" / "scalp.db")

# 등급 값(0부터)의 범위. 화면의 METRICS 순서 [각질, 피지, 탈모, 염증]와 같다. 피지는 0 무 / 1 유.
MAX_GRADES = (2, 1, 2, 2)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY,
    username         TEXT NOT NULL UNIQUE,   -- 로그인 아이디
    name             TEXT NOT NULL,
    gender           TEXT NOT NULL CHECK (gender IN ('female', 'male')),
    role             TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'admin')),
    password_hash    TEXT NOT NULL,
    consent_version  TEXT NOT NULL,          -- 동의한 개인정보 안내 버전
    consented_at     TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,            -- 토큰 원문은 저장하지 않고 해시만 둔다
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

-- 분석 기록. 하루 1건(같은 날짜에 저장하면 덮어쓴다). 사진은 저장하지 않는다.
CREATE TABLE IF NOT EXISTS analyses (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analyzed_on  TEXT NOT NULL,              -- YYYY-MM-DD (한국 날짜)
    dandruff     INTEGER NOT NULL CHECK (dandruff  BETWEEN 0 AND 2),
    sebum        INTEGER NOT NULL CHECK (sebum     BETWEEN 0 AND 1),
    hairloss     INTEGER NOT NULL CHECK (hairloss  BETWEEN 0 AND 2),
    erythema     INTEGER NOT NULL CHECK (erythema  BETWEEN 0 AND 2),
    detail       TEXT,                       -- 확신도·확률 등 JSON (선택)
    is_example   INTEGER NOT NULL DEFAULT 0, -- 시드 계정의 더미 기록
    created_at   TEXT NOT NULL,
    UNIQUE (user_id, analyzed_on)
);

-- 그날 뜬 미션마다 1행. done_at이 비어 있으면 미완료. 뜬 개수가 있어야 지난 날의 달성률을 계산할 수 있다.
CREATE TABLE IF NOT EXISTS daily_mission_log (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date    TEXT NOT NULL,
    mission_id  TEXT NOT NULL,
    done_at     TEXT,
    PRIMARY KEY (user_id, log_date, mission_id)
);

-- 주 루틴 누적 횟수. 주는 월요일부터 일요일.
CREATE TABLE IF NOT EXISTS weekly_mission_log (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_start  TEXT NOT NULL,               -- 그 주 월요일
    mission_id  TEXT NOT NULL,
    count       INTEGER NOT NULL CHECK (count BETWEEN 0 AND 99),
    PRIMARY KEY (user_id, week_start, mission_id)
);
"""


def now_kst() -> datetime:
    return datetime.now(KST)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def today() -> date:
    return now_kst().date()


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI가 의존성과 라우트를 서로 다른 스레드에서 실행할 수 있어 check_same_thread를 끈다
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (iso(now_kst()),))
        conn.commit()
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """요청마다 연결 하나를 열고 끝나면 닫는다. 쓰기는 라우트에서 `with db:`로 묶는다."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
