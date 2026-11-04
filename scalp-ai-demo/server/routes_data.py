"""회원의 분석 기록과 루틴 미션. 모두 로그인이 필요하다.

GET    /api/records                   내 분석 기록 (시드 계정은 더미 기록 포함)
POST   /api/records                   분석 결과 저장 (같은 날짜면 덮어쓴다)
DELETE /api/records                   내가 저장한 기록 삭제 (시드 계정의 더미 기록은 유지)

GET    /api/missions                  일 루틴·주 루틴 전체
PUT    /api/missions/daily/{날짜}      오늘의 일 루틴 저장 (오늘만 가능)
PUT    /api/missions/weekly/{미션id}   이번 주 주 루틴 횟수 저장 (이번 주만 가능)

응답 모양은 화면(dist/app.js)이 브라우저에 저장하던 모양과 같다.
    기록   {id, date, grades:[각질, 피지, 탈모, 염증], sample}
    미션   {daily: {날짜: {shown, done}}, weekly: {월요일: {미션id: 횟수}}}
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

import auth
import db

router = APIRouter(prefix="/api", tags=["data"])

MISSION_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_DETAIL_BYTES = 4000


def parse_date(text: str) -> date:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    raise HTTPException(400, "날짜는 YYYY-MM-DD 형식이어야 해요.")


# ---------------------------------------------------------------- 분석 기록
class RecordIn(BaseModel):
    date: str | None = None                       # 생략하면 오늘
    grades: list[int] = Field(min_length=4, max_length=4)
    detail: dict | None = None                    # 확신도·확률 등 (선택)


def record_json(row: sqlite3.Row) -> dict:
    return {"id": f"rec-{row['id']}", "date": row["analyzed_on"],
            "grades": [row["dandruff"], row["sebum"], row["hairloss"], row["erythema"]],
            "sample": bool(row["is_example"])}


@router.get("/records")
def list_records(user: sqlite3.Row = Depends(auth.current_user), conn: sqlite3.Connection = Depends(db.get_db)):
    rows = conn.execute("SELECT * FROM analyses WHERE user_id = ? ORDER BY analyzed_on", (user["id"],)).fetchall()
    return [record_json(r) for r in rows]


@router.post("/records", status_code=201)
def save_record(body: RecordIn, user: sqlite3.Row = Depends(auth.current_user),
                conn: sqlite3.Connection = Depends(db.get_db)):
    day = parse_date(body.date) if body.date else db.today()
    if day > db.today():
        raise HTTPException(400, "미래 날짜는 저장할 수 없어요.")
    if any(not 0 <= g <= m for g, m in zip(body.grades, db.MAX_GRADES)):
        raise HTTPException(400, "등급 값이 범위를 벗어났어요.")
    detail = json.dumps(body.detail, ensure_ascii=False) if body.detail is not None else None
    if detail and len(detail.encode()) > MAX_DETAIL_BYTES:
        raise HTTPException(400, "상세 정보가 너무 커요.")
    with conn:
        # 같은 날짜의 기록(더미 포함)은 새 결과로 바꾼다
        conn.execute(
            "INSERT INTO analyses (user_id, analyzed_on, dandruff, sebum, hairloss, erythema, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (user_id, analyzed_on) DO UPDATE SET dandruff = excluded.dandruff, sebum = excluded.sebum, "
            "hairloss = excluded.hairloss, erythema = excluded.erythema, detail = excluded.detail, "
            "is_example = 0, created_at = excluded.created_at",
            (user["id"], day.isoformat(), *body.grades, detail, db.iso(db.now_kst())))
    row = conn.execute("SELECT * FROM analyses WHERE user_id = ? AND analyzed_on = ?",
                       (user["id"], day.isoformat())).fetchone()
    return record_json(row)


@router.delete("/records", status_code=204)
def clear_records(user: sqlite3.Row = Depends(auth.current_user), conn: sqlite3.Connection = Depends(db.get_db)):
    with conn:
        conn.execute("DELETE FROM analyses WHERE user_id = ? AND is_example = 0", (user["id"],))


# ---------------------------------------------------------------- 루틴 미션
class DailyIn(BaseModel):
    shown: list[str] = Field(max_length=20)       # 그날 화면에 뜬 미션
    done: list[str] = Field(max_length=20)        # 그중 체크한 미션


class WeeklyIn(BaseModel):
    count: int = Field(ge=0, le=99)


def check_ids(ids: list[str]) -> None:
    if len(set(ids)) != len(ids) or not all(MISSION_ID_RE.match(i) for i in ids):
        raise HTTPException(400, "미션 id가 올바르지 않아요.")


@router.get("/missions")
def get_missions(user: sqlite3.Row = Depends(auth.current_user), conn: sqlite3.Connection = Depends(db.get_db)):
    daily: dict[str, dict] = {}
    for r in conn.execute("SELECT log_date, mission_id, done_at FROM daily_mission_log WHERE user_id = ? "
                          "ORDER BY log_date, rowid", (user["id"],)):
        day = daily.setdefault(r["log_date"], {"shown": [], "done": []})
        day["shown"].append(r["mission_id"])
        if r["done_at"]:
            day["done"].append(r["mission_id"])
    weekly: dict[str, dict] = {}
    for r in conn.execute("SELECT week_start, mission_id, count FROM weekly_mission_log WHERE user_id = ?",
                          (user["id"],)):
        weekly.setdefault(r["week_start"], {})[r["mission_id"]] = r["count"]
    return {"daily": daily, "weekly": weekly}


@router.put("/missions/daily/{day}")
def put_daily(day: str, body: DailyIn, user: sqlite3.Row = Depends(auth.current_user),
              conn: sqlite3.Connection = Depends(db.get_db)):
    if parse_date(day) != db.today():
        raise HTTPException(400, "일 루틴은 오늘 것만 고칠 수 있어요.")
    check_ids(body.shown)
    check_ids(body.done)
    if not set(body.done) <= set(body.shown):
        raise HTTPException(400, "체크한 미션은 오늘 뜬 미션 안에 있어야 해요.")
    now = db.iso(db.now_kst())
    with conn:
        before = {r["mission_id"]: r["done_at"] for r in conn.execute(
            "SELECT mission_id, done_at FROM daily_mission_log WHERE user_id = ? AND log_date = ?", (user["id"], day))}
        conn.execute("DELETE FROM daily_mission_log WHERE user_id = ? AND log_date = ?", (user["id"], day))
        conn.executemany(
            "INSERT INTO daily_mission_log (user_id, log_date, mission_id, done_at) VALUES (?, ?, ?, ?)",
            [(user["id"], day, m, (before.get(m) or now) if m in body.done else None) for m in body.shown])
    return {"shown": body.shown, "done": [m for m in body.shown if m in body.done]}


@router.put("/missions/weekly/{mission_id}")
def put_weekly(mission_id: str, body: WeeklyIn, user: sqlite3.Row = Depends(auth.current_user),
               conn: sqlite3.Connection = Depends(db.get_db)):
    check_ids([mission_id])
    week = db.monday_of(db.today()).isoformat()
    with conn:
        conn.execute(
            "INSERT INTO weekly_mission_log (user_id, week_start, mission_id, count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (user_id, week_start, mission_id) DO UPDATE SET count = excluded.count",
            (user["id"], week, mission_id, body.count))
    return {"weekStart": week, "id": mission_id, "count": body.count}
