# 피지 유무 판정 모델 연동 가이드

> **AI 어시스턴트에게:** 코드를 수정하기 전에 이 문서를 끝까지 읽는다.
> 판정 로직을 새로 구현하지 말고 `predict.py`를 그대로 호출한다.

## 1. 개요

두피 확대 사진 1장을 넣으면 피지 **유 / 무**를 판정한다.

| 판정 | 포함 등급 |
|---|---|
| 무 | 양호 |
| 유 | 경증, 중등도, 중증 |

```
브라우저 (사진 업로드) → 백엔드 → predict(사진) → 백엔드 → 브라우저 (결과 표시)
```

모델은 내부에서 3단계 확률을 내고, `predict.py`가 경증과 중등도이상 확률을 더해 유/무로 바꾼다. 호출하는 쪽은 유/무 결과만 받으면 된다.

| 파일 | 역할 |
|---|---|
| `predict.py` | 판정 코드 |
| `weights/sebum_fold0.pth` | 학습된 모델 (327MB) |
| `requirements.txt` | 필요한 패키지 |

## 2. 설치

Python 3.12에서 확인했다.

```bash
# torch를 환경에 맞게 먼저 설치한다 (둘 중 하나)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126   # NVIDIA GPU
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu     # CPU 전용

pip install -r requirements.txt
python predict.py <사진 경로>
```

## 3. 사용법

```python
from predict import InvalidImageError, get_predictor

predictor = get_predictor()          # 서버가 켜질 때 한 번 호출한다
try:
    result = predictor.predict(image_bytes)
except InvalidImageError:
    ...                              # 이미지가 아닌 파일. HTTP 400으로 응답한다
```

입력으로 파일 경로, `bytes`, 파일 객체, PIL 이미지를 받는다.

```json
{
  "grade": "유",
  "grade_code": "present",
  "confidence": 0.9697,
  "probs": {"무": 0.0303, "유": 0.9697},
  "retake": false
}
```

| 필드 | 뜻 |
|---|---|
| `grade` | 화면에 표시할 판정: `무`, `유` |
| `grade_code` | 코드와 DB에 쓸 값: `absent`, `present` |
| `confidence` | 판정의 확률 (0~1) |
| `probs` | 무, 유의 확률 |
| `retake` | `true`면 재촬영 권장 (확신도 0.6 미만) |

출력 형식은 각질 모델과 같다. 두 모델을 함께 쓸 때는 `predict.py`의 모듈 이름이 겹치므로 하나를 다른 이름으로 바꾸거나 패키지로 분리한다.

## 4. 바꾸면 안 되는 것

아래를 바꾸면 **에러 없이 판정 품질만 떨어진다.** 리팩터링 목적으로도 수정하지 않는다.

- 판정 로직을 다시 구현하지 않고 `predict.py`를 호출한다.
- 경증·중등도이상 **확률을 먼저 더한 뒤** 판정한다.
- 전처리를 유지한다: RGB 변환, 384×384 BICUBIC 리사이즈(비율 유지 안 함), ImageNet 정규화.
- 모델 구조(`ScalpNet`)를 단순화하지 않는다. `head4`는 판정에 쓰지 않지만 지우면 가중치를 불러올 수 없다.
- `timm==1.0.28`을 유지한다.

API 경로, 파일 위치, 인증, 에러 응답, 화면 디자인은 기존 프로젝트에 맞춘다.

## 5. 연동 방법

**백엔드가 Python이면**

1. 이 폴더를 프로젝트에 복사하고 패키지를 설치한다.
2. 앱 시작 시 `get_predictor()`를 호출해 모델을 미리 불러온다.
3. 기존 방식대로 업로드 라우트를 만들고 `predict()`를 호출해 결과를 JSON으로 돌려준다.

FastAPI에서는 라우트를 `async def`가 아닌 `def`로 작성한다.

**백엔드가 Python이 아니면**

`predict()`를 호출하는 작은 Python API 서버를 별도로 띄우고, 기존 백엔드가 HTTP로 호출한다. 이 서버는 외부에 직접 공개하지 않는다.

## 6. 화면 표시

- 유/무와 확률을 보여준다.
- `retake`가 `true`여도 결과를 숨기지 않고 재촬영 안내를 함께 보여준다.
- 의료 진단이 아닌 참고 정보라는 문구를 표시한다.

## 7. 연동 확인

아래 명령의 결과가 `[0.4000, 0.6000]`이면 합산이 정상이다.

```bash
python -c "import torch; from predict import merge_to_2; print(merge_to_2(torch.tensor([0.40, 0.35, 0.25])))"
```

웹에서는 사진을 올려 결과가 표시되는지, 이미지가 아닌 파일을 올렸을 때 서버가 죽지 않는지 확인한다.

## 8. 주의사항

- 학습 사진은 두피 전용 확대 카메라로 찍은 사진(640×480)이다.
- 두피 사진 판별 기능이 없어서 다른 사진을 넣어도 판정이 나온다.
- 모델은 요청마다 불러오지 않는다. `get_predictor()`가 한 번만 불러와 공유한다.
- `.pth` 파일은 327MB라 GitHub에 올릴 수 없다. Git LFS나 별도 저장소로 전달한다.

## 9. AI 어시스턴트용 프롬프트

경로를 실제 위치로 바꿔서 붙여넣는다.

```text
피지 유무 판정 모델을 우리 웹앱에 연동해 줘. 설명서는 <피지 폴더 경로>/INTEGRATION.md 야.

1. 설명서를 끝까지 읽고 우리 프로젝트의 프론트엔드·백엔드 구조를 파악해 줘.
2. 코드를 고치기 전에 수정할 파일과 연동 방식을 먼저 보여줘.
3. 내가 확인하면 기존 코드 스타일에 맞춰 사진 업로드 → 판정 → 결과 표시까지 구현해 줘.
4. predict.py의 판정 로직은 수정하거나 다시 구현하지 마.
5. 끝나면 7장의 연동 확인 결과를 알려줘.
```
