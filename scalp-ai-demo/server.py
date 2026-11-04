"""Serve the existing website and its local four-model inference API."""

from __future__ import annotations

import argparse
import io
import logging
import os
import sqlite3
import warnings
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, send_file, send_from_directory
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from accounts import AccountError, AccountStore, COOKIE_NAME, SESSION_SECONDS
from runtime_identity import SERVICE_ID, installation_id

BASE_DIR = Path(__file__).resolve().parent
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def decode_photo(upload) -> Image.Image:
    payload = upload.read(MAX_FILE_BYTES + 1)
    if not payload or len(payload) > MAX_FILE_BYTES:
        raise ValueError("사진은 장당 10MB 이하의 파일이어야 합니다.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as probe:
                if probe.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("JPG, PNG, WEBP 사진만 사용할 수 있습니다.")
                if probe.width * probe.height > MAX_PIXELS:
                    raise ValueError("사진 해상도는 2,000만 화소 이하여야 합니다.")
                probe.verify()
            with Image.open(io.BytesIO(payload)) as source:
                return ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("읽을 수 없는 사진입니다. JPG, PNG, WEBP 파일을 확인하세요.") from exc


def create_app(service=None, database_path=None) -> Flask:
    app = Flask(__name__, static_folder=str(BASE_DIR / "dist"), static_url_path="")
    app.config.update(MAX_CONTENT_LENGTH=32 * 1024 * 1024, MAX_FORM_PARTS=6)
    # Keep multipart uploads in memory; do not spool scalp photos to a temp file.
    from flask import Request

    class MemoryRequest(Request):
        def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
            return io.BytesIO()

    app.request_class = MemoryRequest
    if service is None:
        from inference import ModelService
        service = ModelService()
        service.start_loading()
    app.extensions["model_service"] = service
    accounts = AccountStore(database_path or os.environ.get("SCALP_DB_PATH") or BASE_DIR / "data" / "scalp.sqlite3")
    app.extensions["account_store"] = accounts

    @app.before_request
    def local_api_context():
        if not request.path.startswith("/api/"):
            return None
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if (origin and origin != request.host_url.rstrip("/")) or request.headers.get("Sec-Fetch-Site") == "cross-site":
                return jsonify(error="이 웹 서버에서 다시 시도해 주세요."), 403
        g.user = accounts.current_user(request.cookies.get(COOKIE_NAME))
        protected = request.path in {"/api/records", "/api/care-checks", "/api/analyze", "/api/auth/profile", "/api/report/pdf"} or request.path.startswith("/api/admin/")
        if protected and "X-Scalp-Account" in request.headers:
            expected_account = str(g.user["id"]) if g.user else "guest"
            if request.headers["X-Scalp-Account"] != expected_account:
                return jsonify(error="계정이 변경됐어요. 로그인 상태를 다시 확인해 주세요.", code="account_changed"), 409
        if protected and "X-Scalp-Result-Epoch" in request.headers:
            expected_epoch = str(g.user["result_epoch"]) if g.user else "0"
            if request.headers["X-Scalp-Result-Epoch"] != expected_epoch:
                return jsonify(error="관리자가 기록을 초기화했어요. 현재 계정의 기록을 다시 확인해 주세요.", code="data_changed"), 409

        if protected and "X-Scalp-Profile-Version" in request.headers:
            expected_version = str(g.user["profile_version"]) if g.user else "0"
            if request.headers["X-Scalp-Profile-Version"] != expected_version:
                return jsonify(error="회원정보가 변경됐어요. 최신 정보로 다시 불러와 주세요.", code="profile_changed"), 409

    def require_user():
        if not g.user:
            raise AccountError("로그인 후 이용해 주세요.", 401)
        return g.user["id"]

    def require_admin():
        user_id = require_user()
        if g.user["role"] != "admin":
            raise AccountError("관리자만 이용할 수 있어요.", 403, "admin_required")
        return user_id

    def confirmed_target(body, user_id):
        if type(body.get("confirm_user_id")) is not int or body["confirm_user_id"] != user_id:
            raise AccountError("초기화하거나 삭제할 계정 번호를 확인해 주세요.")

    def json_body():
        if request.mimetype != "application/json":
            raise AccountError("요청을 처리하지 못했어요. 페이지를 새로고침한 뒤 다시 시도해 주세요.", 415)
        if request.content_length and request.content_length > 512 * 1024:
            raise AccountError("요청 내용이 너무 큽니다.", 413)
        body = request.get_json()
        if not isinstance(body, dict):
            raise AccountError("요청 내용을 확인해 주세요.")
        return body

    def session_response(user, status=200):
        token = accounts.new_session(user["id"], request.cookies.get(COOKIE_NAME), result_epoch=user["result_epoch"])
        response = jsonify(user=user)
        response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=request.is_secure, samesite="Lax", path="/")
        return response, status

    @app.get("/api/auth/me")
    def current_account():
        return jsonify(user=g.user)

    @app.get("/api/auth/nickname")
    def nickname_availability():
        return jsonify(accounts.nickname_available(request.args.get("nickname")))

    @app.get("/api/auth/profile")
    def account_profile():
        return jsonify(user=accounts.profile(require_user()))

    @app.patch("/api/auth/profile")
    def update_account_profile():
        user_id = require_user()
        return session_response(accounts.update_profile(user_id, json_body(), result_epoch=g.user["result_epoch"]))

    @app.post("/api/auth/register")
    def register():
        return session_response(accounts.register(json_body()), 201)

    @app.post("/api/auth/login")
    def login():
        return session_response(accounts.login(json_body()))

    @app.post("/api/auth/logout")
    def logout():
        json_body()
        accounts.logout(request.cookies.get(COOKIE_NAME))
        response = jsonify(user=None)
        response.delete_cookie(COOKIE_NAME, httponly=True, samesite="Lax", path="/")
        return response

    @app.get("/api/records")
    def account_records():
        return jsonify(records=accounts.records(require_user()))

    @app.post("/api/records")
    def save_account_record():
        user_id = require_user()
        record, created = accounts.save_record(user_id, json_body())
        return jsonify(record=record), 201 if created else 200

    @app.delete("/api/records")
    def delete_account_records():
        return jsonify(deleted=accounts.clear_records(require_user(), result_epoch=g.user["result_epoch"]))

    @app.get("/api/care-checks")
    def get_care_checks():
        user_id = require_user()
        if "month" in request.args:
            if "date" in request.args:
                raise AccountError("관리 기록은 날짜 또는 월 하나만 선택해 주세요.")
            return jsonify(accounts.care_month(user_id, request.args.get("month"), result_epoch=g.user["result_epoch"]))
        return jsonify(accounts.care_checks(user_id, request.args.get("date"), result_epoch=g.user["result_epoch"]))

    @app.put("/api/care-checks")
    def save_care_checks():
        user_id = require_user()
        body = json_body()
        if "checks" not in body or body["checks"] is None:
            raise AccountError("관리 체크 항목을 확인해 주세요.")
        return jsonify(accounts.care_checks(user_id, body.get("date"), body["checks"], result_epoch=g.user["result_epoch"]))

    @app.get("/api/admin/overview")
    def admin_overview():
        actor_id = require_admin()
        status = dict(service.health())
        status["error"] = str(service.error)[:2000] if getattr(service, "error", None) else None
        return jsonify(counts=accounts.admin_summary(actor_id), health=status)

    @app.get("/api/admin/users")
    def admin_users():
        return jsonify(users=accounts.admin_users(require_admin()))

    @app.get("/api/admin/actions")
    def admin_actions():
        return jsonify(actions=accounts.admin_actions(require_admin()))

    @app.post("/api/admin/users/<int:user_id>/reset-password")
    def admin_reset_password(user_id):
        actor_id = require_admin()
        json_body()
        return jsonify(accounts.admin_reset_password(actor_id, user_id))

    @app.post("/api/admin/users/<int:user_id>/clear-data")
    def admin_clear_data(user_id):
        actor_id = require_admin()
        confirmed_target(json_body(), user_id)
        return jsonify(accounts.admin_clear_data(actor_id, user_id))

    @app.delete("/api/admin/users/<int:user_id>")
    def admin_delete_user(user_id):
        actor_id = require_admin()
        confirmed_target(json_body(), user_id)
        return jsonify(accounts.admin_delete_user(actor_id, user_id))

    @app.errorhandler(AccountError)
    def account_error(exc):
        payload = {"error": str(exc)}
        if exc.code:
            payload["code"] = exc.code
        return jsonify(payload), exc.status

    @app.errorhandler(sqlite3.Error)
    def database_error(exc):
        app.logger.exception("Account database operation failed")
        return jsonify(error="기록 저장소에 연결하지 못했어요. 잠시 후 다시 시도해 주세요."), 500

    @app.get("/")
    def index():
        return send_from_directory(BASE_DIR / "dist", "index.html")

    @app.get("/api/health")
    def health():
        return jsonify(dict(service.health(), application=SERVICE_ID, installation_id=installation_id(BASE_DIR)))

    @app.post("/api/report/pdf")
    def download_report():
        from report_pdf import ReportFontError, ReportValidationError, build_report_pdf
        body = json_body()
        try:
            payload = build_report_pdf(body.get("result"), profile=g.user)
        except ReportValidationError as exc:
            return jsonify(error=str(exc)), 400
        except ReportFontError as exc:
            app.logger.error("PDF font unavailable: %s", exc)
            return jsonify(error="보고서의 한글 글꼴을 준비하지 못했어요. 잠시 후 다시 시도해 주세요."), 503
        except Exception:
            app.logger.exception("PDF generation failed")
            return jsonify(error="PDF 보고서를 만들지 못했어요. 잠시 후 다시 시도해 주세요."), 500
        return send_file(io.BytesIO(payload), mimetype="application/pdf", as_attachment=True,
                         download_name=f"두피_분석_보고서_{body['result']['date']}.pdf", max_age=0)

    @app.post("/api/analyze")
    def analyze():
        # Local same-origin website only. No permissive CORS for private photos.
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            return jsonify(error="서비스 페이지에서 사진을 다시 선택해 주세요."), 403
        from inference import AnalysisBusy, ModelUnavailable
        images = []
        try:
            uploads = request.files.getlist("photos")
            if set(request.files) - {"photos"} or not 1 <= len(uploads) <= 3:
                raise ValueError("두피 사진을 1~3장 선택하세요.")
            for upload in uploads:
                images.append(decode_photo(upload))
            result = service.analyze(images)
            result["save_token"] = accounts.sign_result(result, g.user["id"] if g.user else None, result_epoch=g.user["result_epoch"] if g.user else 0)
            return jsonify(result)
        except AccountError:
            raise
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except ModelUnavailable:
            return jsonify(error="분석 서비스를 이용할 수 없어요. 잠시 후 다시 시도해 주세요."), 503
        except AnalysisBusy as exc:
            return jsonify(error=str(exc)), 429
        except RequestEntityTooLarge:
            raise
        except Exception:
            app.logger.exception("Inference failed")
            return jsonify(error="분석을 마치지 못했어요. 잠시 후 다시 시도해 주세요."), 500
        finally:
            for image in images:
                image.close()

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_):
        return jsonify(error="업로드 용량을 초과했습니다. 사진은 장당 10MB, 최대 3장입니다."), 413

    @app.errorhandler(HTTPException)
    def http_error(exc):
        if request.path.startswith("/api/"):
            messages = {
                400: "요청 내용을 확인하지 못했어요. 페이지를 새로고침한 뒤 다시 시도해 주세요.",
                404: "요청하신 기능을 찾을 수 없어요. 페이지를 새로고침해 주세요.",
                405: "요청을 처리하지 못했어요. 페이지를 새로고침한 뒤 다시 시도해 주세요.",
            }
            return jsonify(error=messages.get(exc.code, "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.")), exc.code
        title = "페이지를 찾을 수 없어요" if exc.code == 404 else "페이지를 열지 못했어요"
        message = "주소가 바뀌었거나 더 이상 제공되지 않는 페이지예요. 홈에서 원하는 메뉴를 다시 선택해 주세요." if exc.code == 404 else "요청을 처리하지 못했어요. 홈으로 이동한 뒤 다시 시도해 주세요."
        return render_template("error.html", title=title, message=message), exc.code

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="두피 사진 분석 웹 서버")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    from waitress import serve
    print(f"Scalp AI: http://{args.host}:{args.port}", flush=True)
    serve(create_app(), host=args.host, port=args.port, threads=4,
          max_request_body_size=32 * 1024 * 1024,
          inbuf_overflow=33 * 1024 * 1024)
