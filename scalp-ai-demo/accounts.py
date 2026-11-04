"""Local demo accounts and account-owned analysis data backed by SQLite."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

SESSION_SECONDS = 7 * 24 * 60 * 60
COOKIE_NAME = "scalp_session"
GENDER_CONSENT_VERSION = "2026-11-03"
PUBLIC_USER_FIELDS = ("id", "nickname", "role", "result_epoch", "gender", "gender_consent", "profile_version")
CHECK_IDS = frozenset({"gentle-wash", "low-heat", "observe", "flakes-care", "sebum-care", "hair-care", "redness-care"})
METRIC_IDS = ("flakes", "sebum", "hair_loss", "erythema")
RECORD_FIELDS = ("id", "date", "source", "photo_count", "aggregation", "settings_verified", "warnings", "metrics", "per_photo", "elapsed_ms", "configuration_id")
METRIC_FIELDS = ("id", "label", "class_index", "confidence", "probabilities", "class_labels", "settings_verified", "excluded_classes", "grade_index", "labels_confirmed", "grade_probabilities", "grade_labels", "grade_indices", "grade_confidence", "grading_method", "preprocessing_version")


class AccountError(ValueError):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


def valid_date(value):
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def record_payload(value):
    """Keep the browser record contract; omit names, photos and transient tokens."""
    if not isinstance(value, dict):
        raise AccountError("저장할 분석 결과를 확인해 주세요.")
    record = {key: value[key] for key in RECORD_FIELDS if key in value}
    def metric_payload(metric):
        if not isinstance(metric, dict):
            raise AccountError("분석 결과의 항목을 확인해 주세요.")
        return {key: metric[key] for key in METRIC_FIELDS if key in metric and metric[key] is not None}
    if "metrics" in record:
        if not isinstance(record["metrics"], list):
            raise AccountError("분석 결과의 항목을 확인해 주세요.")
        record["metrics"] = [metric_payload(metric) for metric in record["metrics"]]
    if "per_photo" in record:
        if not isinstance(record["per_photo"], list) or any(
            not isinstance(photo, dict) or "index" not in photo or not isinstance(photo.get("metrics"), list)
            for photo in record["per_photo"]
        ):
            raise AccountError("사진별 분석 결과를 확인해 주세요.")
        record["per_photo"] = [
            {"index": photo["index"], "metrics": [metric_payload(metric) for metric in photo["metrics"]]}
            for photo in record["per_photo"]
        ]
    return record


def canonical(value):
    # JSON.stringify turns integer-valued floats into integers. Normalize these
    # before signing so a browser's lossless numeric roundtrip keeps the token.
    def normalized(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, list):
            return [normalized(child) for child in item]
        if isinstance(item, dict):
            return {key: normalized(child) for key, child in item.items()}
        return item
    try:
        payload = json.dumps(normalized(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AccountError("분석 결과의 형식이 올바르지 않습니다.") from exc
    if len(payload.encode("utf-8")) > 256 * 1024:
        raise AccountError("저장할 분석 결과가 너무 큽니다.")
    return payload


class AccountStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nickname TEXT NOT NULL, password_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
                    result_epoch INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS users_nickname ON users(nickname);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS records (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    record_id TEXT NOT NULL, record_date TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(user_id, record_id)
                );
                CREATE TABLE IF NOT EXISTS care_checks (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    check_date TEXT NOT NULL, checks TEXT NOT NULL,
                    PRIMARY KEY(user_id, check_date)
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS admin_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id INTEGER NOT NULL, actor_nickname TEXT NOT NULL,
                    target_id INTEGER NOT NULL, target_nickname TEXT NOT NULL,
                    action TEXT NOT NULL, created_at INTEGER NOT NULL, details TEXT NOT NULL
                );
            """)
            # Serialize idempotent migration across server processes. Existing
            # accounts retain their IDs, hashes, records and sessions as members.
            db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
            if "role" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin'))")
            if "result_epoch" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN result_epoch INTEGER NOT NULL DEFAULT 0")
            additions = {
                "nickname_key": "TEXT",
                "gender": "TEXT CHECK(gender IN ('male','female') OR gender IS NULL)",
                "gender_consent": "INTEGER NOT NULL DEFAULT 0 CHECK(gender_consent IN (0,1))",
                "gender_consented_at": "INTEGER",
                "gender_consent_version": "TEXT",
                "profile_version": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
            for row in db.execute("SELECT id,nickname FROM users WHERE nickname_key IS NULL OR nickname_key='' ").fetchall():
                db.execute("UPDATE users SET nickname_key=? WHERE id=?", (self.nickname_key(row["nickname"]), row["id"]))
            # Historical duplicates keep their IDs and data. New writes are
            # serialized and reject a matching normalized key, even if a caller
            # bypasses the UI availability check.
            db.execute("CREATE INDEX IF NOT EXISTS users_nickname_key ON users(nickname_key)")
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES ('signing_secret',?)", (secrets.token_hex(32),))
            self.signing_secret = db.execute("SELECT value FROM metadata WHERE key='signing_secret'").fetchone()[0].encode()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def nickname_key(nickname):
        return unicodedata.normalize("NFKC", nickname.strip()).casefold()

    @classmethod
    def nickname_value(cls, nickname):
        if (not isinstance(nickname, str) or not 1 <= len(nickname.strip()) <= 40
                or any(unicodedata.category(character).startswith("C") for character in nickname)):
            raise AccountError("아이디를 1~40자로 입력해 주세요.")
        return nickname.strip()

    @classmethod
    def credentials(cls, body):
        nickname, password = cls.nickname_value(body.get("nickname")), body.get("password")
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            raise AccountError("비밀번호를 1~128자로 입력해 주세요.")
        return nickname, password

    @staticmethod
    def gender_details(body, previous=None):
        previous = dict(previous) if previous is not None else {}
        gender = body.get("gender", previous.get("gender"))
        consent = body.get("gender_consent", bool(previous.get("gender_consent", False)))
        if gender not in (None, "male", "female") or type(consent) is not bool:
            raise AccountError("성별 선택과 정보 활용 동의 여부를 확인해 주세요.")
        if not consent:
            if "gender" in body and gender is not None:
                raise AccountError("성별 정보 활용에 동의하거나 성별 선택을 해제해 주세요.")
            return None, False
        if gender is None:
            raise AccountError("정보 활용에 동의하려면 성별을 선택해 주세요.")
        return gender, True

    @staticmethod
    def public_user(row):
        if row is None:
            return None
        result = {key: row[key] for key in PUBLIC_USER_FIELDS}
        result["gender_consent"] = bool(result["gender_consent"])
        if not result["gender_consent"]:
            result["gender"] = None
        return result

    def nickname_available(self, nickname):
        nickname = self.nickname_value(nickname)
        with self.connection() as db:
            exists = db.execute("SELECT 1 FROM users WHERE nickname_key=? LIMIT 1", (self.nickname_key(nickname),)).fetchone()
        return {"nickname": nickname, "available": exists is None}

    @classmethod
    def _unique_nickname(cls, db, nickname, exclude_id=None):
        duplicate = db.execute("SELECT 1 FROM users WHERE nickname_key=? AND id!=? LIMIT 1",
                               (cls.nickname_key(nickname), exclude_id if exclude_id is not None else -1)).fetchone()
        if duplicate:
            raise AccountError("이미 사용 중인 아이디예요. 다른 아이디를 입력해 주세요.", 409, "nickname_taken")

    def register(self, body):
        # Public signup always creates an ordinary account, regardless of input.
        return self._create_user(body, "user")

    def create_admin(self, nickname, password):
        """Operator-only entry point, exposed by the local CLI, never an HTTP route."""
        return self._create_user({"nickname": nickname, "password": password}, "admin")

    def _create_user(self, body, role):
        nickname, password = self.credentials(body)
        gender, consent = self.gender_details(body)
        password_hash = generate_password_hash(password)
        now = int(time.time())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._unique_nickname(db, nickname)
            cursor = db.execute("INSERT INTO users(nickname,nickname_key,password_hash,created_at,role,gender,gender_consent,gender_consented_at,gender_consent_version) VALUES (?,?,?,?,?,?,?,?,?)",
                                (nickname, self.nickname_key(nickname), password_hash, now, role, gender, int(consent),
                                 now if consent else None, GENDER_CONSENT_VERSION if consent else None))
            user = self.public_user(db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())
            if role == "admin":
                self._audit(db, user, user, "admin_created", {})
            return user

    def login(self, body):
        nickname, password = self.credentials(body)
        with self.connection() as db:
            candidates = db.execute("SELECT * FROM users WHERE nickname_key=? ORDER BY (nickname=?) DESC,id",
                                    (self.nickname_key(nickname), nickname)).fetchall()
        # Historical duplicate accounts remain accessible by their original
        # credentials; normalization never merges or deletes their records.
        for row in candidates:
            if check_password_hash(row["password_hash"], password):
                return self.public_user(row)
        raise AccountError("아이디와 비밀번호를 다시 확인해 주세요.", 401)

    def profile(self, user_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise AccountError("로그인 후 이용해 주세요.", 401)
        return self.public_user(row)

    def update_profile(self, user_id, body, result_epoch=None):
        current_password = body.get("current_password")
        if not isinstance(current_password, str) or not 1 <= len(current_password) <= 128:
            raise AccountError("회원정보를 수정하려면 현재 비밀번호를 입력해 주세요.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_epoch(db, user_id, result_epoch)
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row["role"] != "user":
                raise AccountError("관리자 계정 정보는 로컬 운영 도구에서 변경해 주세요.", 403)
            if not check_password_hash(row["password_hash"], current_password):
                raise AccountError("현재 비밀번호가 맞지 않아요. 다시 확인해 주세요.", 403, "password_mismatch")
            nickname = self.nickname_value(body.get("nickname", row["nickname"]))
            if nickname != row["nickname"]:
                self._unique_nickname(db, nickname, user_id)
            gender, consent = self.gender_details(body, row)
            password_hash = row["password_hash"]
            password_changed = False
            if "new_password" in body:
                new_password = body["new_password"]
                if not isinstance(new_password, str) or not 1 <= len(new_password) <= 128:
                    raise AccountError("새 비밀번호를 1~128자로 입력해 주세요.")
                if not check_password_hash(password_hash, new_password):
                    password_hash = generate_password_hash(new_password)
                    password_changed = True
            changed = nickname != row["nickname"] or gender != row["gender"] or consent != bool(row["gender_consent"]) or password_changed
            if changed:
                consent_changed = gender != row["gender"] or consent != bool(row["gender_consent"])
                consent_at = (int(time.time()) if consent else None) if consent_changed else row["gender_consented_at"]
                consent_version = (GENDER_CONSENT_VERSION if consent else None) if consent_changed else row["gender_consent_version"]
                db.execute("UPDATE users SET nickname=?,nickname_key=?,password_hash=?,gender=?,gender_consent=?,gender_consented_at=?,gender_consent_version=?,profile_version=profile_version+1,result_epoch=result_epoch+1 WHERE id=?",
                           (nickname, self.nickname_key(nickname), password_hash, gender, int(consent), consent_at, consent_version, user_id))
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            return self.public_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def update_admin_credentials(self, user_id, nickname, password):
        """Local operator maintenance; never exposed through a web route."""
        nickname, password = self.credentials({"nickname": nickname, "password": password})
        password_hash = generate_password_hash(password)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = self._require_admin(db, user_id)
            self._unique_nickname(db, nickname, user_id)
            db.execute("UPDATE users SET nickname=?,nickname_key=?,password_hash=?,result_epoch=result_epoch+1,profile_version=profile_version+1 WHERE id=?",
                       (nickname, self.nickname_key(nickname), password_hash, user_id))
            revoked = db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,)).rowcount
            user = self.public_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
            self._audit(db, actor, user, "admin_credentials_updated", {"revoked_sessions": revoked})
            return user

    def new_session(self, user_id, old_token=None, result_epoch=None):
        token = secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_epoch(db, user_id, result_epoch)
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            if old_token:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (self.token_hash(old_token),))
            db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (?,?,?)", (self.token_hash(token), user_id, int(time.time()) + SESSION_SECONDS))
        return token

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def current_user(self, token):
        if not token or len(token) > 200:
            return None
        with self.connection() as db:
            row = db.execute("SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=? AND sessions.expires_at>?", (self.token_hash(token), int(time.time()))).fetchone()
        return self.public_user(row)

    def logout(self, token):
        if token:
            with self.connection() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (self.token_hash(token),))

    @staticmethod
    def _epoch(db, user_id):
        if user_id is None:
            return 0
        row = db.execute("SELECT result_epoch FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise AccountError("로그인 후 이용해 주세요.", 401)
        return row["result_epoch"]

    @classmethod
    def _check_epoch(cls, db, user_id, expected):
        current = cls._epoch(db, user_id)
        if expected is not None and expected != current:
            raise AccountError("관리자가 기록 또는 비밀번호를 초기화했어요. 로그인 상태를 다시 확인해 주세요.", 409, "data_changed")
        return current

    def _signed_payload(self, record, user_id, epoch):
        digest = hashlib.sha256(canonical(record).encode()).hexdigest()
        message = f"{user_id if user_id is not None else 'guest'}.{epoch}.{digest}"
        return message + "." + hmac.new(self.signing_secret, message.encode(), hashlib.sha256).hexdigest()

    def sign_result(self, result, user_id, result_epoch=None):
        if result_epoch is None:
            with self.connection() as db:
                result_epoch = self._epoch(db, user_id)
        # An in-flight analysis keeps the epoch captured at request start, so a
        # reset during inference cannot accidentally issue a fresh valid proof.
        return self._signed_payload(record_payload(result), user_id, result_epoch)

    def save_record(self, user_id, body):
        record = record_payload(body.get("record"))
        token = body.get("save_token") or body["record"].get("save_token")
        with self.connection() as db:
            # Proof verification and insertion share a write transaction with
            # administrator cleanup. An old page cannot restore cleared data.
            db.execute("BEGIN IMMEDIATE")
            expected = self._signed_payload(record, user_id, self._epoch(db, user_id))
            if not isinstance(token, str) or not token.isascii() or len(token) > 200 or not hmac.compare_digest(token, expected):
                raise AccountError("이 계정에서 현재 설정으로 분석한 결과만 저장할 수 있어요. 사진을 다시 분석해 주세요.", 403)
            if (set(record) != set(RECORD_FIELDS) or record["source"] != "model"
                    or not isinstance(record["id"], str) or not 1 <= len(record["id"]) <= 200
                    or not valid_date(record["date"]) or record["aggregation"] != "mean_probabilities"
                    or type(record["photo_count"]) is not int or not 1 <= record["photo_count"] <= 3
                    or len(record["metrics"]) != 4 or tuple(metric["id"] for metric in record["metrics"]) != METRIC_IDS
                    or len(record["per_photo"]) != record["photo_count"]):
                raise AccountError("저장할 분석 결과의 형식이 올바르지 않습니다.")
            payload = canonical(record)
            cursor = db.execute("INSERT OR IGNORE INTO records(user_id,record_id,record_date,payload) VALUES (?,?,?,?)", (user_id, record["id"], record["date"], payload))
            created = cursor.rowcount == 1
            saved = json.loads(db.execute("SELECT payload FROM records WHERE user_id=? AND record_id=?", (user_id, record["id"])).fetchone()[0])
        return saved, created

    def records(self, user_id):
        with self.connection() as db:
            rows = db.execute("SELECT payload FROM records WHERE user_id=? ORDER BY record_date, rowid", (user_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def clear_records(self, user_id, result_epoch=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_epoch(db, user_id, result_epoch)
            return db.execute("DELETE FROM records WHERE user_id=?", (user_id,)).rowcount

    def care_checks(self, user_id, check_date, checks=None, result_epoch=None):
        if not valid_date(check_date):
            raise AccountError("관리 기록의 날짜를 확인해 주세요.")
        if checks is not None and check_date > datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat():
            raise AccountError("미래 날짜에는 관리 실천을 기록할 수 없어요.")
        if checks is not None and (not isinstance(checks, list) or len(checks) > len(CHECK_IDS)
                                  or any(not isinstance(item, str) or item not in CHECK_IDS for item in checks)
                                  or len(set(checks)) != len(checks)):
            raise AccountError("관리 체크 항목을 확인해 주세요.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE" if checks is not None else "BEGIN")
            self._check_epoch(db, user_id, result_epoch)
            if checks is not None:
                db.execute("INSERT INTO care_checks(user_id,check_date,checks) VALUES (?,?,?) ON CONFLICT(user_id,check_date) DO UPDATE SET checks=excluded.checks", (user_id, check_date, json.dumps(sorted(checks))))
            row = db.execute("SELECT checks FROM care_checks WHERE user_id=? AND check_date=?", (user_id, check_date)).fetchone()
        return {"date": check_date, "checks": json.loads(row[0]) if row else []}

    def care_month(self, user_id, month, result_epoch=None):
        if not isinstance(month, str) or len(month) != 7 or not valid_date(month + "-01"):
            raise AccountError("조회할 월을 YYYY-MM 형식으로 선택해 주세요.")
        with self.connection() as db:
            db.execute("BEGIN")
            self._check_epoch(db, user_id, result_epoch)
            rows = db.execute("SELECT check_date,checks FROM care_checks WHERE user_id=? AND check_date>=? AND check_date<=? ORDER BY check_date",
                              (user_id, month + "-01", month + "-31")).fetchall()
        return {"month": month, "days": [{"date": row["check_date"], "checks": json.loads(row["checks"])} for row in rows]}

    @staticmethod
    def _require_admin(db, actor_id):
        row = db.execute("SELECT id,nickname,role,result_epoch FROM users WHERE id=?", (actor_id,)).fetchone()
        if row is None:
            raise AccountError("로그인 후 이용해 주세요.", 401)
        if row["role"] != "admin":
            raise AccountError("관리자만 이용할 수 있어요.", 403, "admin_required")
        return row

    @staticmethod
    def _member_target(db, target_id):
        if type(target_id) is not int or target_id <= 0:
            raise AccountError("관리할 계정 번호를 확인해 주세요.")
        row = db.execute("SELECT id,nickname,role,result_epoch FROM users WHERE id=?", (target_id,)).fetchone()
        if row is None:
            raise AccountError("해당 계정을 찾을 수 없어요. 목록을 다시 불러와 주세요.", 404)
        if row["role"] != "user":
            raise AccountError("관리자 계정은 이 화면에서 변경하거나 삭제할 수 없어요.", 403)
        return row

    @staticmethod
    def _audit(db, actor, target, action, details):
        # Snapshot IDs and names intentionally survive removal of the target.
        db.execute("INSERT INTO admin_actions(actor_id,actor_nickname,target_id,target_nickname,action,created_at,details) VALUES (?,?,?,?,?,?,?)", (
            actor["id"], actor["nickname"], target["id"], target["nickname"], action,
            int(time.time()), json.dumps(details, ensure_ascii=False, separators=(",", ":")),
        ))

    def admin_summary(self, actor_id):
        with self.connection() as db:
            db.execute("BEGIN")
            self._require_admin(db, actor_id)
            users = db.execute("SELECT COUNT(*) AS accounts,COALESCE(SUM(role='user'),0) AS members,COALESCE(SUM(role='admin'),0) AS admins FROM users").fetchone()
            return {**dict(users), "records": db.execute("SELECT COUNT(*) FROM records").fetchone()[0],
                    "care_days": db.execute("SELECT COUNT(*) FROM care_checks").fetchone()[0]}

    def admin_users(self, actor_id):
        with self.connection() as db:
            db.execute("BEGIN")
            self._require_admin(db, actor_id)
            rows = db.execute("SELECT u.id,u.nickname,u.role,u.created_at,(SELECT COUNT(*) FROM records r WHERE r.user_id=u.id) AS record_count,(SELECT COUNT(*) FROM care_checks c WHERE c.user_id=u.id) AS care_days FROM users u ORDER BY u.id").fetchall()
            return [dict(row) for row in rows]

    def admin_actions(self, actor_id, limit=50):
        with self.connection() as db:
            db.execute("BEGIN")
            self._require_admin(db, actor_id)
            rows = db.execute("SELECT * FROM admin_actions ORDER BY id DESC LIMIT ?", (min(max(int(limit),1),200),)).fetchall()
            return [{**dict(row), "details": json.loads(row["details"])} for row in rows]

    def admin_reset_password(self, actor_id, target_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = self._require_admin(db, actor_id)
            target = self._member_target(db, target_id)
            existing_hashes = [row[0] for row in db.execute("SELECT password_hash FROM users WHERE nickname_key=?", (self.nickname_key(target["nickname"]),))]
            for _ in range(20):
                temporary = f"{secrets.randbelow(100_000_000):08d}"
                if not any(check_password_hash(value, temporary) for value in existing_hashes):
                    break
            else:
                raise AccountError("임시 비밀번호를 만들지 못했어요. 다시 시도해 주세요.", 409)
            db.execute("UPDATE users SET password_hash=?,result_epoch=result_epoch+1 WHERE id=?", (generate_password_hash(temporary), target_id))
            revoked = db.execute("DELETE FROM sessions WHERE user_id=?", (target_id,)).rowcount
            self._audit(db, actor, target, "password_reset", {"revoked_sessions": revoked})
            return {"user": {key: target[key] for key in ("id", "nickname", "role")},
                    "temporary_password": temporary, "revoked_sessions": revoked}

    def admin_clear_data(self, actor_id, target_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = self._require_admin(db, actor_id)
            target = self._member_target(db, target_id)
            records = db.execute("DELETE FROM records WHERE user_id=?", (target_id,)).rowcount
            care = db.execute("DELETE FROM care_checks WHERE user_id=?", (target_id,)).rowcount
            db.execute("UPDATE users SET result_epoch=result_epoch+1 WHERE id=?", (target_id,))
            self._audit(db, actor, target, "data_cleared", {"deleted_records": records, "deleted_care_days": care})
            return {"user_id": target_id, "deleted_records": records, "deleted_care_days": care}

    def admin_delete_user(self, actor_id, target_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = self._require_admin(db, actor_id)
            target = self._member_target(db, target_id)
            records = db.execute("SELECT COUNT(*) FROM records WHERE user_id=?", (target_id,)).fetchone()[0]
            care = db.execute("SELECT COUNT(*) FROM care_checks WHERE user_id=?", (target_id,)).fetchone()[0]
            sessions = db.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (target_id,)).fetchone()[0]
            db.execute("DELETE FROM users WHERE id=?", (target_id,))
            self._audit(db, actor, target, "user_deleted", {"deleted_records": records, "deleted_care_days": care, "revoked_sessions": sessions})
            return {"deleted_user_id": target_id, "deleted_records": records,
                    "deleted_care_days": care, "revoked_sessions": sessions}
