"""두피 분석 API 서버.

    python -m uvicorn app:app --port 8000        (server 폴더에서 실행)

POST /api/analyze        사진 1장(multipart, 필드 이름 photo) → 지표 4개의 판정 (게스트도 사용 가능)
GET  /api/health         서버와 모델 상태
/api/auth/*              회원가입·로그인 (routes_auth.py)
/api/records, /api/missions   회원의 분석 기록·루틴 미션 (routes_data.py)
그 외 경로는 ../dist 의 화면을 그대로 내려준다.

SCALP_SKIP_MODELS=1 이면 모델을 불러오지 않는다(DB·회원 기능만 확인할 때).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import db
import routes_auth
import routes_data
import seed

DIST_DIR = Path(__file__).resolve().parents[1] / "dist"
MAX_BYTES = 15 * 1024 * 1024        # 사진 최대 크기
SKIP_MODELS = os.environ.get("SCALP_SKIP_MODELS") == "1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    conn = db.connect()
    try:
        seed.ensure_accounts(conn)  # 어드민·일반 계정이 없으면 만든다
    finally:
        conn.close()
    if not SKIP_MODELS:
        from scalp import engine
        engine.load_models()        # 요청마다 불러오지 않도록 시작할 때 한 번만 불러온다
    yield


app = FastAPI(title="Scalp analysis API", lifespan=lifespan)
app.include_router(routes_auth.router)
app.include_router(routes_data.router)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    fields = [".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()]
    return JSONResponse({"detail": "입력값을 확인해 주세요.", "fields": fields}, status_code=422)


@app.get("/api/health")
def health():
    return {"status": "ok", "models": not SKIP_MODELS}


# async def가 아닌 def: 모델 추론은 CPU/GPU를 오래 쓰므로 FastAPI가 스레드풀에서 실행한다.
@app.post("/api/analyze")
def analyze(photo: UploadFile = File(...)):
    from scalp import engine
    raw = photo.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "사진은 15MB 이하여야 해요.")
    try:
        return engine.analyze(raw)
    except engine.InvalidImageError:
        raise HTTPException(400, "이미지가 아닌 파일이에요.")


class RevalidatedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


if DIST_DIR.is_dir():
    app.mount("/", RevalidatedStaticFiles(directory=DIST_DIR, html=True), name="dist")
