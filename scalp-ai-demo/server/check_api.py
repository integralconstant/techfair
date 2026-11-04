"""회원·기록·미션 API 점검. 모델은 불러오지 않고, 임시 DB로 실행한다.

    python check_api.py        (server 폴더에서, httpx 필요)
"""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["SCALP_DB"] = str(Path(tmp) / "check.db")
os.environ["SCALP_SKIP_MODELS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

import app as server  # noqa: E402
import db  # noqa: E402
import seed  # noqa: E402

failures = []


def check(name, ok, info=""):
    if not ok:
        failures.append(name)
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  -> {info}"))


today = db.today()
monday = db.monday_of(today)
TODAY, YESTERDAY = today.isoformat(), (today - timedelta(days=1)).isoformat()
SIGNUP = {"username": "Kim_01", "name": "김두피", "gender": "male", "password": "pass1234", "consent": True}

with TestClient(server.app) as guest, TestClient(server.app) as kim, TestClient(server.app) as lee, \
        TestClient(server.app) as demo, TestClient(server.app) as admin:
    print("== 게스트 ==")
    check("health", guest.get("/api/health").json()["status"] == "ok")
    for path in ("/api/auth/me", "/api/records", "/api/missions"):
        check(f"게스트 {path} 401", guest.get(path).status_code == 401)
    check("게스트 기록 저장 401", guest.post("/api/records", json={"grades": [0, 0, 0, 0]}).status_code == 401)
    check("정적 화면 제공", guest.get("/").status_code == 200)

    print("== 회원가입 ==")
    r = kim.post("/api/auth/signup", json={**SIGNUP, "consent": False})
    check("동의 없으면 400", r.status_code == 400 and "동의" in r.json()["detail"], r.text)
    check("아이디 형식 400", kim.post("/api/auth/signup", json={**SIGNUP, "username": "a b"}).status_code == 400)
    check("성별 값 422", kim.post("/api/auth/signup", json={**SIGNUP, "gender": "x"}).status_code == 422)
    check("admin 아이디는 가입 불가 409", kim.post("/api/auth/signup", json={**SIGNUP, "username": "admin"}).status_code == 409)
    r = kim.post("/api/auth/signup", json={**SIGNUP, "password": "short"})
    check("짧은 비밀번호 422(한글 메시지)", r.status_code == 422 and "확인" in r.json()["detail"], r.text)
    check("동의 항목 누락 422", kim.post("/api/auth/signup", json={k: v for k, v in SIGNUP.items() if k != "consent"}).status_code == 422)
    r = kim.post("/api/auth/signup", json=SIGNUP)
    check("가입 201 + 로그인 상태", r.status_code == 201 and kim.get("/api/auth/me").json()["username"] == "kim_01", r.text)
    check("성별·역할 반환", r.json()["gender"] == "male" and r.json()["role"] == "member", r.text)
    check("쿠키는 HttpOnly", "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower())
    check("응답에 비밀번호 없음", "password" not in r.text)
    check("중복 아이디(대소문자 무시) 409", lee.post("/api/auth/signup", json={**SIGNUP, "username": "kim_01"}).status_code == 409)

    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE username = 'kim_01'").fetchone()
    check("비밀번호는 해시로 저장", row["password_hash"].startswith("pbkdf2_sha256$") and "pass1234" not in row["password_hash"])
    check("동의 버전·시각 기록", bool(row["consent_version"]) and bool(row["consented_at"]))
    tok = kim.cookies.get("scalp_session")
    check("세션 토큰 원문은 DB에 없음", conn.execute("SELECT COUNT(*) FROM sessions WHERE token_hash = ?", (tok,)).fetchone()[0] == 0)
    conn.close()

    print("== 로그인/로그아웃 ==")
    check("틀린 비밀번호 401", lee.post("/api/auth/login", json={"username": "kim_01", "password": "wrongpass1"}).status_code == 401)
    check("없는 아이디 401(같은 메시지)", lee.post("/api/auth/login", json={"username": "nobody", "password": "wrongpass1"}).json()["detail"]
          == lee.post("/api/auth/login", json={"username": "kim_01", "password": "wrongpass1"}).json()["detail"])
    check("로그인 200", lee.post("/api/auth/login", json={"username": " KIM_01 ", "password": "pass1234"}).status_code == 200)
    check("로그아웃 204 후 401", lee.post("/api/auth/logout").status_code == 204 and lee.get("/api/auth/me").status_code == 401)
    check("다른 기기 세션은 유지", kim.get("/api/auth/me").status_code == 200)

    print("== 분석 기록 ==")
    check("새 회원 기록 비어 있음", kim.get("/api/records").json() == [])
    r = kim.post("/api/records", json={"grades": [1, 0, 1, 0], "detail": {"confidence": 0.7}})
    check("저장 201, 오늘 날짜", r.status_code == 201 and r.json()["date"] == TODAY and r.json()["grades"] == [1, 0, 1, 0], r.text)
    kim.post("/api/records", json={"grades": [2, 1, 2, 2]})
    recs = kim.get("/api/records").json()
    check("같은 날짜는 덮어쓰기", len(recs) == 1 and recs[0]["grades"] == [2, 1, 2, 2], recs)
    check("피지 2 거부", kim.post("/api/records", json={"grades": [0, 2, 0, 0]}).status_code == 400)
    check("각질 3 거부", kim.post("/api/records", json={"grades": [3, 0, 0, 0]}).status_code == 400)
    check("음수 거부", kim.post("/api/records", json={"grades": [0, 0, -1, 0]}).status_code == 400)
    check("길이 3 거부", kim.post("/api/records", json={"grades": [0, 0, 0]}).status_code == 422)
    check("미래 날짜 거부", kim.post("/api/records", json={"date": (today + timedelta(days=1)).isoformat(), "grades": [0, 0, 0, 0]}).status_code == 400)
    check("날짜 형식 거부", kim.post("/api/records", json={"date": "2026-13-40", "grades": [0, 0, 0, 0]}).status_code == 400)
    kim.post("/api/records", json={"date": YESTERDAY, "grades": [1, 1, 1, 1]})
    check("날짜순 정렬", [x["date"] for x in kim.get("/api/records").json()] == [YESTERDAY, TODAY])

    print("== 일 루틴 ==")
    shown = ["c_rinse", "c_dry", "d_lather"]
    r = kim.put(f"/api/missions/daily/{TODAY}", json={"shown": shown, "done": ["c_dry"]})
    check("오늘 저장", r.status_code == 200 and r.json() == {"shown": shown, "done": ["c_dry"]}, r.text)
    kim.put(f"/api/missions/daily/{TODAY}", json={"shown": shown, "done": ["c_dry", "c_rinse"]})
    m = kim.get("/api/missions").json()
    check("체크 추가·순서 유지", m["daily"][TODAY] == {"shown": shown, "done": ["c_rinse", "c_dry"]}, m)
    conn = db.connect()
    first = conn.execute("SELECT done_at FROM daily_mission_log WHERE log_date = ? AND mission_id = 'c_dry'", (TODAY,)).fetchone()[0]
    kim.put(f"/api/missions/daily/{TODAY}", json={"shown": shown, "done": ["c_dry"]})
    again = conn.execute("SELECT done_at FROM daily_mission_log WHERE log_date = ? AND mission_id = 'c_dry'", (TODAY,)).fetchone()[0]
    check("체크 시각은 처음 값 유지", first == again)
    check("체크 해제 → done_at 비움", conn.execute("SELECT done_at FROM daily_mission_log WHERE log_date = ? AND mission_id = 'c_rinse'", (TODAY,)).fetchone()[0] is None)
    conn.close()
    check("어제 일 루틴은 읽기 전용", kim.put(f"/api/missions/daily/{YESTERDAY}", json={"shown": shown, "done": []}).status_code == 400)
    check("뜨지 않은 미션 체크 거부", kim.put(f"/api/missions/daily/{TODAY}", json={"shown": shown, "done": ["h_loose"]}).status_code == 400)
    check("중복 id 거부", kim.put(f"/api/missions/daily/{TODAY}", json={"shown": ["c_dry", "c_dry"], "done": []}).status_code == 400)
    check("이상한 id 거부", kim.put(f"/api/missions/daily/{TODAY}", json={"shown": ["../x"], "done": []}).status_code == 400)

    print("== 주 루틴 ==")
    r = kim.put("/api/missions/weekly/w_no_heat", json={"count": 3})
    check("이번 주 저장", r.status_code == 200 and r.json()["weekStart"] == monday.isoformat(), r.text)
    kim.put("/api/missions/weekly/w_no_heat", json={"count": 4})
    check("덮어쓰기", kim.get("/api/missions").json()["weekly"][monday.isoformat()] == {"w_no_heat": 4})
    check("횟수 100 거부", kim.put("/api/missions/weekly/w_no_heat", json={"count": 100}).status_code == 422)
    check("횟수 -1 거부", kim.put("/api/missions/weekly/w_no_heat", json={"count": -1}).status_code == 422)

    print("== 회원 간 분리 ==")
    lee.post("/api/auth/signup", json={"username": "lee", "name": "이두피", "gender": "female", "password": "pass5678", "consent": True})
    check("다른 회원은 내 기록을 못 봄", lee.get("/api/records").json() == [] and lee.get("/api/missions").json() == {"daily": {}, "weekly": {}})

    print("== 시드 계정 ==")
    check("일반 계정 로그인", demo.post("/api/auth/login", json={"username": "demo", "password": "demo1234"}).json()["role"] == "member")
    me = admin.post("/api/auth/login", json={"username": "admin", "password": "12345"}).json()
    check("어드민 로그인(role=admin)", me.get("role") == "admin", me)
    check("어드민도 더미 기록 49건", len(admin.get("/api/records").json()) == 49)
    check("새 회원에게는 더미 기록 없음", lee.get("/api/records").json() == [])
    recs = demo.get("/api/records").json()
    check("예시 기록 49건, 모두 sample", len(recs) == 49 and all(x["sample"] for x in recs), len(recs))
    check("첫/마지막 기록", recs[0]["date"] == "2026-05-04" and recs[-1]["date"] == "2026-10-23" and recs[-1]["grades"] == [1, 0, 1, 0])
    m = demo.get("/api/missions").json()
    days = sorted(m["daily"])
    check("일 루틴 56일, 어제까지", len(days) == 56 and days[-1] == YESTERDAY and TODAY not in m["daily"], (len(days), days[-1:]))
    check("done ⊆ shown", all(set(v["done"]) <= set(v["shown"]) for v in m["daily"].values()))
    weeks = sorted(m["weekly"])
    check("주 루틴은 지난 주까지(월요일 키)", bool(weeks) and all(w < monday.isoformat() and date.fromisoformat(w).weekday() == 0 for w in weeks), weeks)
    early = sum(len(v["done"]) / len(v["shown"]) for d, v in m["daily"].items() if d in days[:14]) / 14
    late = sum(len(v["done"]) / len(v["shown"]) for d, v in m["daily"].items() if d in days[-14:]) / 14
    check("달성률이 올라가는 흐름", late > early + 0.2, (round(early, 2), round(late, 2)))
    check("같은 날짜 저장 → 예시 기록을 새 결과로 교체", demo.post("/api/records", json={"date": "2026-10-23", "grades": [0, 0, 0, 0]}).status_code == 201
          and [x for x in demo.get("/api/records").json() if x["date"] == "2026-10-23"][0]["sample"] is False)
    check("내 기록 삭제 후 예시는 유지", demo.post("/api/records", json={"grades": [1, 1, 1, 1]}).status_code == 201
          and demo.delete("/api/records").status_code == 204 and len(demo.get("/api/records").json()) == 48)

    print("== 시드 계정 다시 만들기 ==")
    conn = db.connect()
    seed.seed_account(conn, seed.ACCOUNTS[1])
    n = conn.execute("SELECT COUNT(*) FROM analyses a JOIN users u ON u.id = a.user_id WHERE u.username = 'demo'").fetchone()[0]
    check("재생성 시 기록 49건으로 복구", n == 49, n)
    seed.ensure_accounts(conn)
    check("ensure_accounts는 기존 계정을 그대로 둠", conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 4)
    check("이전 세션은 계정 재생성으로 무효", demo.get("/api/auth/me").status_code == 401)
    check("어드민 세션은 유지", admin.get("/api/auth/me").status_code == 200)
    conn.close()

print()
print("ALL OK" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
