"""두피 각질 심각도 판정 모듈.

두피 확대 사진 1장을 받아 양호 / 경중등도 / 중증 3단계 판정과 확률을 돌려준다.
웹 프레임워크에 의존하지 않으므로 어떤 Python 백엔드에서도 그대로 호출할 수 있다.

    from predict import get_predictor

    result = get_predictor().predict("photo.jpg")     # 경로, bytes, 파일 객체, PIL 이미지 모두 가능

판정 순서 (INTEGRATION.md 4장의 "바꾸면 안 되는 것" 참고)
    1. 사진을 RGB로 변환하고 384×384로 맞춘 뒤 정규화한다.
    2. 모델이 4단계(양호·경증·중등도·중증) 확률을 낸다.
    3. 경증과 중등도 확률을 더해 3단계 확률로 만든다.
    4. 가장 큰 확률의 등급을 판정 결과로 삼는다.
"""
from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import BinaryIO, Sequence, Union

import timm
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, UnidentifiedImageError
from torchvision import transforms
from torchvision.transforms import InterpolationMode

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR.parents[1] / "models"
DEFAULT_WEIGHTS = [MODELS_DIR / "seed42_fold0.pth"]

BACKBONE = "vit_base_patch16_dinov3.lvd1689m"
IMG_SIZE = 384
DROPOUT = 0.3                       # eval에서는 동작하지 않지만 모델 구조를 맞추는 데 필요하다
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

MERGE_MAP = [0, 1, 1, 2]            # 양호→0, 경증→1, 중등도→1, 중증→2
GRADES = ["양호", "경중등도", "중증"]
GRADE_CODES = ["normal", "mild_moderate", "severe"]
RETAKE_THRESHOLD = 0.6              # 확신도가 이 값보다 낮으면 재촬영을 권한다

ImageInput = Union[str, Path, bytes, BinaryIO, Image.Image]


class InvalidImageError(ValueError):
    """이미지로 읽을 수 없는 입력. 웹에서는 400 응답으로 처리한다."""


class ScalpClassifier(nn.Module):
    """DINOv3 백본 + 경량 분류 head. CLS 토큰과 패치 평균을 이어 붙여 4단계로 분류한다."""

    def __init__(self):
        super().__init__()
        self.backbone = timm.create_model(BACKBONE, pretrained=False, num_classes=0,
                                          img_size=IMG_SIZE)
        self.num_prefix = getattr(self.backbone, "num_prefix_tokens", 1)
        d = self.backbone.num_features
        self.head = nn.Sequential(
            nn.LayerNorm(d * 2),
            nn.Dropout(p=DROPOUT),
            nn.Linear(d * 2, len(MERGE_MAP)),
        )

    def forward(self, x):
        tokens = self.backbone.forward_features(x)
        cls = tokens[:, 0]
        patch_mean = tokens[:, self.num_prefix:].mean(1)
        return self.head(torch.cat([cls, patch_mean], dim=1))


def merge_to_3(p4: torch.Tensor) -> torch.Tensor:
    """4단계 확률을 3단계 확률로 합산한다. 등급을 고르기 전에 반드시 먼저 호출한다."""
    p3 = torch.zeros(max(MERGE_MAP) + 1, dtype=p4.dtype, device=p4.device)
    for j, c in enumerate(MERGE_MAP):
        p3[c] += p4[j]
    return p3


def load_image(image: ImageInput) -> Image.Image:
    """지원하는 입력을 RGB PIL 이미지로 변환한다."""
    try:
        if isinstance(image, Image.Image):
            return image.convert("RGB")
        if isinstance(image, (bytes, bytearray)):
            image = io.BytesIO(image)
        with Image.open(image) as img:
            return img.convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImageError(f"이미지를 읽을 수 없다: {e}") from e


class ScalpPredictor:
    """가중치를 불러 판정을 수행한다. 불러오는 데 시간이 걸리므로 서버당 한 번만 만든다.

    Args:
        weights: 가중치 경로 목록. 여러 개를 주면 4단계 확률을 평균한다(앙상블).
        device: "cuda" / "cpu". 생략하면 GPU가 있을 때 GPU를 쓴다.
        retake_threshold: 확신도가 이 값보다 낮으면 결과의 retake가 True가 된다.
    """

    def __init__(self, weights: Sequence[Union[str, Path]] | None = None, device: str | None = None,
                 retake_threshold: float = RETAKE_THRESHOLD):
        self.retake_threshold = retake_threshold
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.amp_dtype = torch.bfloat16
        if self.device.type == "cuda" and not torch.cuda.is_bf16_supported():
            self.amp_dtype = torch.float16

        self.models = []
        for path in weights or DEFAULT_WEIGHTS:
            model = ScalpClassifier()
            model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
            self.models.append(model.to(self.device).eval())

        self.transform = transforms.Compose([
            transforms.Resize((IMG_SIZE, IMG_SIZE), interpolation=InterpolationMode.BICUBIC),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ])

    @torch.inference_mode()
    def predict(self, image: ImageInput) -> dict:
        """사진 1장을 판정한다.

        Returns:
            {"grade": "경중등도", "grade_code": "mild_moderate", "confidence": 0.643,
             "probs": {"양호": 0.01, "경중등도": 0.643, "중증": 0.347}, "retake": False}

        Raises:
            InvalidImageError: 입력을 이미지로 읽을 수 없을 때.
        """
        x = self.transform(load_image(image)).unsqueeze(0).to(self.device)
        with torch.autocast(self.device.type, dtype=self.amp_dtype,
                            enabled=self.device.type == "cuda"):
            logits = [model(x) for model in self.models]
        p4 = torch.stack([F.softmax(lg.float(), dim=1)[0] for lg in logits]).mean(0)

        p3 = merge_to_3(p4)
        idx = int(p3.argmax())
        confidence = float(p3[idx])
        return {
            "grade": GRADES[idx],
            "grade_code": GRADE_CODES[idx],
            "confidence": round(confidence, 4),
            "probs": {g: round(float(v), 4) for g, v in zip(GRADES, p3)},
            "retake": confidence < self.retake_threshold,
        }


_predictor = None
_lock = threading.Lock()


def get_predictor() -> ScalpPredictor:
    """프로세스당 하나의 ScalpPredictor를 만들어 돌려준다. 여러 요청이 재사용해도 안전하다."""
    global _predictor
    if _predictor is None:
        with _lock:
            if _predictor is None:
                _predictor = ScalpPredictor()
    return _predictor


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("사용법: python predict.py <사진 경로>")
    print(json.dumps(get_predictor().predict(sys.argv[1]), ensure_ascii=False, indent=2))
