"""두피 피지 유무 판정 모듈.

두피 확대 사진 1장을 받아 유 / 무 판정과 확률을 돌려준다.
웹 프레임워크에 의존하지 않으므로 어떤 Python 백엔드에서도 그대로 호출할 수 있다.

    from predict import get_predictor

    result = get_predictor().predict("photo.jpg")     # 경로, bytes, 파일 객체, PIL 이미지 모두 가능

판정 순서 (INTEGRATION.md 4장의 "바꾸면 안 되는 것" 참고)
    1. 사진을 RGB로 변환하고 384×384로 맞춘 뒤 정규화한다.
    2. 모델이 3단계(양호·경증·중등도이상) 확률을 낸다.
    3. 경증과 중등도이상 확률을 더해 유 / 무 확률로 만든다.
    4. 더 큰 확률의 쪽을 판정 결과로 삼는다.
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
DEFAULT_WEIGHTS = [MODELS_DIR / "sebum_fold0.pth"]

BACKBONE = "vit_base_patch16_dinov3.lvd1689m"
IMG_SIZE = 384
FUSE_BLOCKS = 4                     # 마지막 N개 블록의 토큰을 함께 쓴다
DROPOUT = 0.3                       # eval에서는 동작하지 않지만 모델 구조를 맞추는 데 필요하다
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

MERGE_MAP = [0, 1, 1]               # 양호→무, 경증→유, 중등도이상→유
GRADES = ["무", "유"]
GRADE_CODES = ["absent", "present"]
RETAKE_THRESHOLD = 0.6              # 확신도가 이 값보다 낮으면 재촬영을 권한다

ImageInput = Union[str, Path, bytes, BinaryIO, Image.Image]


class InvalidImageError(ValueError):
    """이미지로 읽을 수 없는 입력. 웹에서는 400 응답으로 처리한다."""


class AttnPool(nn.Module):
    """학습되는 질의 벡터 하나로 패치 토큰을 가중평균한다."""

    def __init__(self, dim: int):
        super().__init__()
        self.q = nn.Parameter(torch.zeros(dim))
        self.scale = dim ** -0.5

    def forward(self, tokens):
        w = (tokens @ self.q) * self.scale
        w = w.softmax(dim=1).unsqueeze(-1)
        return (tokens * w).sum(1)


class ScalpNet(nn.Module):
    """DINOv3 백본 + 마지막 4개 블록의 어텐션 풀링 head.

    head4는 학습 때 쓰인 보조 출력이다. 판정에는 쓰지 않지만 가중치를 불러오려면 있어야 한다.
    """

    def __init__(self):
        super().__init__()
        self.backbone = timm.create_model(BACKBONE, pretrained=False, num_classes=0,
                                          img_size=IMG_SIZE)
        self.num_prefix = getattr(self.backbone, "num_prefix_tokens", 1)
        d = self.backbone.num_features
        self.block_norms = nn.ModuleList([nn.LayerNorm(d) for _ in range(FUSE_BLOCKS)])
        self.pools = nn.ModuleList([AttnPool(d) for _ in range(FUSE_BLOCKS)])
        feat_dim = d * FUSE_BLOCKS * 2      # 블록마다 (CLS, pooled)
        self.head = self._make_head(feat_dim, len(MERGE_MAP))
        self.head4 = self._make_head(feat_dim, 4)

    @staticmethod
    def _make_head(feat_dim: int, num_classes: int) -> nn.Sequential:
        return nn.Sequential(
            nn.LayerNorm(feat_dim),
            nn.Dropout(p=DROPOUT),
            nn.Linear(feat_dim, num_classes),
        )

    def forward(self, x):
        b = self.backbone
        x = b.patch_embed(x)
        x, rot_pos_embed = b._pos_embed(x)
        x = b.norm_pre(x)

        mixed = getattr(b, "rope_mixed", False) and rot_pos_embed is not None
        outs = []
        n_blk = len(b.blocks)
        for i, blk in enumerate(b.blocks):
            x = blk(x, rope=rot_pos_embed[i] if mixed else rot_pos_embed)
            if i >= n_blk - FUSE_BLOCKS:
                outs.append(x)

        feats = []
        for j, t in enumerate(outs):
            t = self.block_norms[j](t)
            feats += [t[:, 0], self.pools[j](t[:, self.num_prefix:])]
        return self.head(torch.cat(feats, dim=1))


def merge_to_2(p3: torch.Tensor) -> torch.Tensor:
    """3단계 확률을 유 / 무 확률로 합산한다. 판정을 고르기 전에 반드시 먼저 호출한다."""
    p2 = torch.zeros(max(MERGE_MAP) + 1, dtype=p3.dtype, device=p3.device)
    for j, c in enumerate(MERGE_MAP):
        p2[c] += p3[j]
    return p2


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
        weights: 가중치 경로 목록. 여러 개를 주면 3단계 확률을 평균한다(앙상블).
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
            model = ScalpNet()
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
            {"grade": "유", "grade_code": "present", "confidence": 0.93,
             "probs": {"무": 0.07, "유": 0.93}, "retake": False}

        Raises:
            InvalidImageError: 입력을 이미지로 읽을 수 없을 때.
        """
        x = self.transform(load_image(image)).unsqueeze(0).to(self.device)
        with torch.autocast(self.device.type, dtype=self.amp_dtype,
                            enabled=self.device.type == "cuda"):
            logits = [model(x) for model in self.models]
        p3 = torch.stack([F.softmax(lg.float(), dim=1)[0] for lg in logits]).mean(0)

        p2 = merge_to_2(p3)
        idx = int(p2.argmax())
        confidence = float(p2[idx])
        return {
            "grade": GRADES[idx],
            "grade_code": GRADE_CODES[idx],
            "confidence": round(confidence, 4),
            "probs": {g: round(float(v), 4) for g, v in zip(GRADES, p2)},
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
