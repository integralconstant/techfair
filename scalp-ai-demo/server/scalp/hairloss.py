"""두피 탈모 심각도 판정 모듈.

두피 확대 사진 1장을 받아 정상 / 경증 / 중증 3단계 판정과 확률을 돌려준다.
모델은 처음부터 3단계(정상, 경증+중등도, 중증)로 학습되어 확률 합산이 필요 없다.
인터페이스는 keratin.py와 같다: get_predictor().predict(image) -> dict

학습 코드가 없어서 가중치의 층 구조(torchvision EfficientNet-B4, 출력 3개)에서 모델을 복원했다.
입력 크기(IMG_SIZE)와 정규화는 확인하지 못한 가정값이다.
"""
from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import BinaryIO, Sequence, Union

import torch
import torch.nn.functional as F
from PIL import Image, UnidentifiedImageError
from torchvision import transforms
from torchvision.models import efficientnet_b4
from torchvision.transforms import InterpolationMode

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR.parents[1] / "models"
DEFAULT_WEIGHTS = [MODELS_DIR / "best_model_v11_augment_탈모.pth"]

IMG_SIZE = 384                      # 가정값: EfficientNet-B4 권장 입력(380~384)
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

GRADES = ["정상", "경증", "중증"]
GRADE_CODES = ["normal", "mild_moderate", "severe"]
RETAKE_THRESHOLD = 0.6              # 확신도가 이 값보다 낮으면 재촬영을 권한다

ImageInput = Union[str, Path, bytes, BinaryIO, Image.Image]


class InvalidImageError(ValueError):
    """이미지로 읽을 수 없는 입력. 웹에서는 400 응답으로 처리한다."""


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
    """가중치를 불러 판정을 수행한다. 불러오는 데 시간이 걸리므로 서버당 한 번만 만든다."""

    def __init__(self, weights: Sequence[Union[str, Path]] | None = None, device: str | None = None,
                 retake_threshold: float = RETAKE_THRESHOLD):
        self.retake_threshold = retake_threshold
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.amp_dtype = torch.bfloat16
        if self.device.type == "cuda" and not torch.cuda.is_bf16_supported():
            self.amp_dtype = torch.float16

        self.models = []
        for path in weights or DEFAULT_WEIGHTS:
            model = efficientnet_b4(weights=None, num_classes=len(GRADES))
            model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
            self.models.append(model.to(self.device).eval())

        self.transform = transforms.Compose([
            transforms.Resize((IMG_SIZE, IMG_SIZE), interpolation=InterpolationMode.BICUBIC),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ])

    @torch.inference_mode()
    def predict(self, image: ImageInput) -> dict:
        """사진 1장을 판정한다. 반환 형식은 keratin.py와 같다."""
        x = self.transform(load_image(image)).unsqueeze(0).to(self.device)
        with torch.autocast(self.device.type, dtype=self.amp_dtype,
                            enabled=self.device.type == "cuda"):
            logits = [model(x) for model in self.models]
        p3 = torch.stack([F.softmax(lg.float(), dim=1)[0] for lg in logits]).mean(0)

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
        raise SystemExit("사용법: python -m scalp.hairloss <사진 경로>")
    print(json.dumps(get_predictor().predict(sys.argv[1]), ensure_ascii=False, indent=2))
