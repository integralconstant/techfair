# 두피 분석 API 서버

사진 1장을 받아 지표 4개(각질, 피지, 탈모, 염증)를 판정하고, 회원의 분석 기록과 루틴 미션을 SQLite에 저장합니다.

## 실행

Python 3.12, `server` 폴더에서 실행합니다. 가중치는 `../models`에 있어야 합니다.

```bash
# torch를 환경에 맞게 먼저 설치한다 (둘 중 하나)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126   # NVIDIA GPU
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu     # CPU 전용

pip install -r requirements.txt
python -m uvicorn app:app --port 8000
```

`http://localhost:8000/`에서 화면(`../dist`)도 함께 열립니다. 서버가 켜질 때 DB 파일(`data/scalp.db`)과 시드 계정을 만들고 모델 4개를 불러옵니다. 서버 전체가 메모리를 약 1.7GB 씁니다.

| 환경변수 | 뜻 |
|---|---|
| `SCALP_DB` | DB 파일 경로 (기본 `server/data/scalp.db`) |
| `SCALP_SKIP_MODELS=1` | 모델을 불러오지 않음 (회원·DB 기능만 확인할 때) |
| `SCALP_COOKIE_SECURE=1` | https로 배포할 때 로그인 쿠키에 Secure 지정 |
| `SCALP_ADMIN_PASSWORD` | 어드민 비밀번호 (기본 `12345`). 계정을 처음 만들 때 적용 |

## 시드 계정

서버가 켜질 때 계정이 없으면 자동으로 만듭니다. 더미 기록은 이 두 계정에만 들어가고, 새로 가입한 회원은 빈 기록으로 시작합니다.

| 아이디 | 비밀번호 | 역할 | 용도 |
|---|---|---|---|
| `admin` | `12345` | `admin` | 화면에서 게스트/회원 보기, 남성/여성, 결과 지정 전환 |
| `demo` | `demo1234` | `member` | 그래프와 미션을 보여 주는 일반 계정 (여성) |

두 계정 모두 분석 기록 49건(5월 → 10월, 점차 좋아지는 흐름)과 계정을 만든 날 기준 과거 8주의 루틴 기록이 들어 있습니다. 시연 직전에 날짜를 오늘로 다시 맞추려면 실행하세요. 두 계정에 저장한 기록은 함께 지워집니다.

```bash
python seed.py --reset
```

학생 체험은 로그인 없이 쓰는 게스트 모드입니다. 게스트는 `/api/analyze`만 쓸 수 있고 서버에 아무것도 저장되지 않습니다.

## API

오류 응답은 항상 `{"detail": "메시지"}` 형식이고, 입력 형식 오류(422)에는 `fields`가 더 붙습니다.

### 판정 (게스트도 사용 가능)

`POST /api/analyze` — multipart, 필드 이름 `photo`, 사진 1장(15MB 이하)

```json
{
  "indicators": {
    "dandruff": {"name": "각질", "grade": 1, "code": "mild_moderate", "label": "경증",
                 "probs": {"정상": 0.01, "경증": 0.64, "중증": 0.35}},
    "sebum":    {"name": "피지", "grade": 1, "code": "present", "label": "유", "...": "..."},
    "hairloss": {"...": "..."},
    "erythema": {"...": "..."}
  }
}
```

`grade`는 화면의 지표 id별 등급 값입니다(각질·탈모·염증 0 정상 / 1 경증 / 2 중증, 피지 0 무 / 1 유). `probs`는 등급별 확률로, 화면에는 표시하지 않습니다. 이미지가 아니면 400, 15MB 초과는 413입니다.

### 회원

| 요청 | 설명 |
|---|---|
| `POST /api/auth/signup` | `{username(영문 소문자·숫자·밑줄 3~20자), name, gender(female/male), password(8자 이상), consent}` — `consent`가 `true`여야 가입되고, 가입과 동시에 로그인됩니다. 중복 아이디는 409 |
| `POST /api/auth/login` | `{username, password}` — 실패 시 401 (아이디/비밀번호 어느 쪽이 틀렸는지 알려 주지 않음) |
| `POST /api/auth/logout` | 204 |
| `GET /api/auth/me` | `{id, username, name, gender, role, since}`. 로그인 전이면 401 |

로그인은 `HttpOnly` 쿠키(`scalp_session`, 7일)로 유지합니다. 아래 API는 모두 로그인이 필요하고 401을 돌려줍니다.

### 분석 기록

| 요청 | 설명 |
|---|---|
| `GET /api/records` | `[{id, date, grades:[각질, 피지, 탈모, 염증], sample}]` 날짜순. `sample`은 시드 계정의 더미 기록 |
| `POST /api/records` | `{date?, grades:[4개], detail?}` — 날짜를 생략하면 오늘. 같은 날짜는 덮어쓰고, 미래 날짜와 범위를 벗어난 등급은 400 |
| `DELETE /api/records` | 내가 저장한 기록 삭제(더미 기록은 유지) |

### 루틴 미션

| 요청 | 설명 |
|---|---|
| `GET /api/missions` | `{daily: {날짜: {shown, done}}, weekly: {월요일: {미션id: 횟수}}}` |
| `PUT /api/missions/daily/{날짜}` | `{shown, done}` — 오늘 날짜만 가능, `done`은 `shown`의 부분집합 |
| `PUT /api/missions/weekly/{미션id}` | `{count}` — 이번 주(월~일)만 가능, 0~99 |


## DB

SQLite 파일 하나입니다. 테이블 정의는 [db.py](db.py)의 `SCHEMA`에 있습니다.

| 테이블 | 내용 |
|---|---|
| `users` | 아이디, 이름, 성별, 역할(member/admin), 비밀번호 해시(PBKDF2), 동의한 안내 버전·시각 |
| `sessions` | 로그인 세션. 토큰 원문은 저장하지 않고 해시만 저장 |
| `analyses` | 분석 기록. 회원당 하루 1건, 지표별 등급 + 선택 상세 JSON. 사진은 저장하지 않음 |
| `daily_mission_log` | 그날 뜬 미션마다 1행(`done_at`이 비면 미완료). 뜬 개수가 있어야 지난 날의 달성률을 구할 수 있음 |
| `weekly_mission_log` | 주 루틴 누적 횟수(`week_start`는 그 주 월요일) |

## 구성

| 파일 | 역할 |
|---|---|
| `app.py` | FastAPI 앱, 판정 라우트, 화면 파일 제공 |
| `db.py`, `auth.py` | DB 연결·테이블·날짜 도구, 비밀번호 해시·세션 |
| `routes_auth.py`, `routes_data.py` | 회원 / 기록·미션 라우트 |
| `seed.py`, `seed_data/` | 시드 계정과 더미 데이터 |
| `check_api.py` | 회원·기록·미션 API 점검(임시 DB 사용, 모델 불필요). `pip install httpx` 후 `python check_api.py` |
| `scalp/engine.py` | 지표 4개 판정 |
| `scalp/keratin.py`, `scalp/sebum.py` | 각질·피지 모델 (`INTEGRATION.md`의 `predict.py`에서 가중치 경로만 바꿈) |
| `scalp/hairloss.py`, `scalp/inflammation.py` | 탈모·염증 모델 (학습 코드가 없어 가중치 구조에서 복원) |

## 알아둘 점

- **전처리 가정:** 탈모(EfficientNet-B4, 384×384)와 염증(ViT-B 패치 14, 392×392)의 입력 크기, 정규화(ImageNet), 리사이즈 방식은 학습 코드가 없어서 가정한 값입니다. 가중치는 오류 없이 불러와지지만, 학습과 다르면 에러 없이 정확도만 떨어집니다. 정답 데이터로 아직 확인하지 않았습니다.
- **시연용 보안 수준:** 비밀번호 해시, 세션 쿠키(HttpOnly), 입력 검증은 갖췄지만 로그인 시도 횟수 제한은 없고 어드민 비밀번호가 단순합니다. 서버를 외부 네트워크에 열지 마세요. 공개 서비스로 쓰려면 https, 시도 제한, 개인정보 처리방침과 삭제 기능이 더 필요합니다.
- **개인정보 동의:** 가입 화면에 안내와 동의 항목 2개가 있고, 서버는 동의 시각과 안내 버전(`routes_auth.py`의 `CONSENT_VERSION`)을 기록합니다. 실제 파기·열람 기능은 없습니다.
- **어드민 보기:** 게스트/회원 보기, 성별, 결과 지정은 화면에서만 바뀝니다. 서버 권한과는 무관합니다.
- **판정 결과 저장:** `/api/analyze`는 결과를 돌려주기만 합니다. 저장은 화면에서 `POST /api/records`로 따로 요청합니다(지금 화면의 "저장" 버튼 흐름과 같음). 서버는 보낸 등급을 그대로 믿습니다.


## 계정 관리

로그인 후 상단 **계정 관리** (`#account`)에서 이름·성별 수정, 비밀번호 변경, 회원 탈퇴를 진행합니다.

- `PATCH /api/auth/me`: 본인 이름·성별 수정
- `PUT /api/auth/password`: 현재 비밀번호 확인 후 변경; 기존 세션 폐기 후 현재 브라우저 세션 재발급
- `DELETE /api/auth/me`: 비밀번호와 `confirmation: "탈퇴"` 확인; 계정·세션·분석·루틴 기록 삭제. 기본 `admin`/`demo` 계정은 탈퇴 불가

검증: server 폴더에서 `python -m unittest test_account` (실제 DB가 아닌 메모리 DB 사용). API 변경 반영에는 서버 재시작이 필요합니다.
