"""4개 지표 판정을 묶는 모듈.

사진 1장을 지표별 모델에 넣고 등급을 고른다.
각 모델의 predict()는 수정하지 않고 그대로 호출한다. 확률 합산(경증+중등도 등)은 모델 모듈 안에서 이미 끝나 있다.

화면(dist/app.js)의 지표 id와 등급 값(0부터)에 맞춰 응답을 만든다.
    dandruff 각질  0 정상 / 1 경증 / 2 중증
    sebum    피지  0 무   / 1 유
    hairloss 탈모  0 정상 / 1 경증 / 2 중증
    erythema 염증  0 정상 / 1 경증 / 2 중증
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Sequence

from . import hairloss, inflammation, keratin, sebum

InvalidImageError = (keratin.InvalidImageError, sebum.InvalidImageError,
                     hairloss.InvalidImageError, inflammation.InvalidImageError)


@dataclass(frozen=True)
class Indicator:
    id: str                 # 화면의 지표 id
    name: str
    module: ModuleType
    labels: Sequence[str]   # 등급 값(0부터)에 대응하는 사용자 표시 이름
    codes: Sequence[str]    # 코드와 DB에 쓸 값


INDICATORS = [
    Indicator("dandruff", "각질", keratin, ["정상", "경증", "중증"], ["normal", "mild_moderate", "severe"]),
    Indicator("sebum", "피지", sebum, ["무", "유"], ["absent", "present"]),
    Indicator("hairloss", "탈모", hairloss, ["정상", "경증", "중증"], ["normal", "mild_moderate", "severe"]),
    Indicator("erythema", "염증", inflammation, ["정상", "경증", "중증"], ["normal", "mild_moderate", "severe"]),
]


def load_models() -> None:
    """서버가 켜질 때 한 번 호출해 모든 모델을 미리 불러온다."""
    for ind in INDICATORS:
        ind.module.get_predictor()


def analyze(photo: bytes) -> dict:
    """사진 1장을 판정해 지표별 결과를 돌려준다.

    Raises:
        InvalidImageError: 이미지로 읽을 수 없는 파일일 때.
    """
    indicators = {}
    for ind in INDICATORS:
        probs = list(ind.module.get_predictor().predict(photo)["probs"].values())
        grade = max(range(len(probs)), key=probs.__getitem__)
        indicators[ind.id] = {
            "name": ind.name,
            "grade": grade,
            "code": ind.codes[grade],
            "label": ind.labels[grade],
            "probs": dict(zip(ind.labels, probs)),
        }
    return {"indicators": indicators}
