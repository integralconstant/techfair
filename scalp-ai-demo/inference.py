"""Load the supplied state dictionaries without executing checkpoint pickle code."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import timm
import torch
from PIL import Image
from torch import nn
from torchvision import models, transforms
from torchvision.transforms import InterpolationMode

BASE_DIR = Path(__file__).resolve().parent
EXPECTED_IDS = ["flakes", "sebum", "hair_loss", "erythema"]
GRADE_LABELS = ("정상", "경증", "중증")
UNVERIFIED_WARNING = (
    "학습 당시 전처리·DINO 특징 결합이 확인되지 않았습니다. "
    "현재 추론 설정에서 계산한 관찰 참고용 결과이며 의료 진단을 대신하지 않습니다."
)


class ModelUnavailable(RuntimeError):
    pass


class AnalysisBusy(RuntimeError):
    pass


class DinoClassifier(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        self.backbone = timm.create_model(
            config["architecture"], pretrained=False, num_classes=0,
            img_size=config["input_size"],
        )
        self.pooling = config["pooling"]
        activation = {"identity": nn.Identity, "gelu": nn.GELU, "relu": nn.ReLU}
        self.head = nn.Sequential(
            nn.LayerNorm(1536), activation[config["head_activation"]](),
            nn.Linear(1536, config["num_classes"]),
        )

    def forward(self, image):
        tokens = self.backbone.forward_features(image)
        cls = tokens[:, 0]
        patches = tokens[:, self.backbone.num_prefix_tokens:].mean(dim=1)
        parts = (cls, patches) if self.pooling == "cls_mean" else (patches, cls)
        return self.head(torch.cat(parts, dim=1))


def build_transform(config: dict):
    """Match the evaluation transform; square resizing is distinct from cropping."""
    interpolation = InterpolationMode(config["interpolation"])
    if config.get("resize_mode", "short_side_crop") == "squash":
        steps = [transforms.Resize((config["input_size"], config["input_size"]), interpolation=interpolation)]
    else:
        steps = [
            transforms.Resize(config["resize_size"], interpolation=interpolation),
            transforms.CenterCrop(config["input_size"]),
        ]
    return transforms.Compose([
        *steps, transforms.ToTensor(), transforms.Normalize(mean=config["mean"], std=config["std"]),
    ])


def read_config(path: Path) -> list[dict]:
    configs = json.loads(path.read_text(encoding="utf-8"))["models"]
    if [c["id"] for c in configs] != EXPECTED_IDS:
        raise ValueError("모델 설정은 flakes, sebum, hair_loss, erythema 순서여야 합니다.")
    for c in configs:
        if c["num_classes"] != (4 if c["id"] == "flakes" else 3):
            raise ValueError(f"{c['id']}: 체크포인트 출력 수와 클래스 수가 다릅니다.")
        if c["architecture"] not in {
            "vit_base_patch16_dinov3", "vit_base_patch14_dinov2", "efficientnet_b4"
        }:
            raise ValueError("지원하지 않는 모델 구조입니다.")
        if not (32 <= c["input_size"] <= c["resize_size"] <= 1024):
            raise ValueError("이미지 크기 설정이 올바르지 않습니다.")
        if c.get("resize_mode", "short_side_crop") not in {"short_side_crop", "squash"}:
            raise ValueError("지원하지 않는 이미지 크기 변환 방식입니다.")
        if c.get("resize_mode") == "squash" and c["input_size"] != c["resize_size"]:
            raise ValueError("정사각 직접 리사이즈는 입력 크기와 리사이즈 크기가 같아야 합니다.")
        if c["interpolation"] not in {"bicubic", "bilinear", "nearest"}:
            raise ValueError("지원하지 않는 보간법입니다.")
        if any(len(c[k]) != 3 for k in ("mean", "std")) or any(v <= 0 for v in c["std"]):
            raise ValueError("정규화 설정이 올바르지 않습니다.")
        if c.get("pooling", "cls_mean") not in {"cls_mean", "mean_cls"}:
            raise ValueError("지원하지 않는 특징 결합입니다.")
        if c.get("head_activation", "identity") not in {"identity", "gelu", "relu"}:
            raise ValueError("지원하지 않는 head 활성화입니다.")
        classifier = c.get("classifier", "default")
        if classifier not in {"default", "sebum_attention_fusion"}:
            raise ValueError("지원하지 않는 분류기 구현입니다.")
        if classifier == "sebum_attention_fusion" and (
            c["id"] != "sebum" or c["architecture"] != "vit_base_patch16_dinov3"
            or c["input_size"] != 384 or c.get("resize_mode") != "squash"
        ):
            raise ValueError("새 피지 분류기는 DINOv3의 384 정사각 입력을 사용해야 합니다.")
        bundled = c.get("bundled_path")
        if bundled is not None and (
            not isinstance(bundled, str) or not bundled
            or Path(bundled).is_absolute() or not (BASE_DIR / bundled).resolve().is_relative_to(BASE_DIR)
        ):
            raise ValueError("내장 모델 경로는 프로젝트 안의 상대 경로여야 합니다.")
        labels = c.get("labels")
        if labels is not None and (
            not isinstance(labels, list) or len(labels) != c["num_classes"]
            or not all(isinstance(v, str) and 0 < len(v) < 100 for v in labels)
        ):
            raise ValueError("클래스 이름은 출력 순서에 맞는 문자열 배열이어야 합니다.")
        if c.get("settings_verified") is True and not labels:
            raise ValueError("학습 설정 확인 완료에는 클래스 이름이 필요합니다.")
        if type(c.get("labels_confirmed", False)) is not bool:
            raise ValueError("등급 매핑 확인 상태는 true 또는 false여야 합니다.")
        excluded = c.get("excluded_classes", [])
        if (
            not isinstance(excluded, list)
            or any(type(v) is not int or not 0 <= v < c["num_classes"] for v in excluded)
            or len(set(excluded)) != len(excluded) or len(excluded) >= c["num_classes"]
        ):
            raise ValueError("제외 클래스는 중복 없는 유효한 번호여야 하며 전체 출력을 제외할 수 없습니다.")
        grades = c.get("grade_indices")
        if grades is not None and (
            not isinstance(grades, list) or len(grades) != c["num_classes"]
            or any(v is not None and (type(v) is not int or not 0 <= v <= 2) for v in grades)
            or any(grades[i] is not None for i in excluded)
        ):
            raise ValueError("클래스별 등급은 0~2이며 제외 클래스는 null이어야 합니다.")
        method = c.get("grading_method", "argmax")
        if method not in {"argmax", "probability_merge"}:
            raise ValueError("지원하지 않는 등급 산출 방식입니다.")
        grade_labels = c.get("grade_labels", list(GRADE_LABELS))
        if (
            not isinstance(grade_labels, list) or len(grade_labels) not in {2, 3}
            or (len(grade_labels) == 2 and c["id"] != "sebum")
            or not all(isinstance(v, str) and 0 < len(v) < 100 for v in grade_labels)
            or len(set(grade_labels)) != len(grade_labels)
        ):
            raise ValueError("최종 판정 이름은 서로 다른 문자열이어야 하며 피지 유무는 2개, 등급은 3개입니다.")
        if grades is not None and any(v is not None and v >= len(grade_labels) for v in grades):
            raise ValueError("클래스 매핑이 최종 판정 범위를 벗어났습니다.")
        if method == "probability_merge" and (excluded or grades is None or any(v is None for v in grades)):
            raise ValueError("확률 합산은 모든 원시 클래스를 최종 등급에 포함해야 합니다.")
        if c.get("labels_confirmed") is True:
            if not labels or grades is None or any(
                grades[i] is None or (method == "argmax" and labels[i] != grade_labels[grades[i]])
                for i in range(c["num_classes"]) if i not in excluded
            ):
                raise ValueError("확인된 클래스 이름과 등급 매핑이 일치해야 합니다.")
        expected_sha = c.get("expected_sha256")
        if expected_sha is not None and (
            not isinstance(expected_sha, str) or len(expected_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_sha)
        ):
            raise ValueError("가중치 SHA256은 소문자 16진수 64자리여야 합니다.")
    return configs


class ModelService:
    def __init__(self, model_dir: Path | None = None, config_path: Path | None = None):
        self.configs = read_config(config_path or BASE_DIR / "model_config.json")
        self._explicit_model_dir = model_dir is not None or bool(os.environ.get("SCALP_MODEL_DIR"))
        self.model_dir = model_dir or self._find_model_dir()
        requested_device = os.environ.get("SCALP_DEVICE", "cpu")
        if requested_device not in {"cpu", "cuda"}:
            raise ValueError("SCALP_DEVICE는 cpu 또는 cuda여야 합니다.")
        if requested_device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA를 사용할 수 없습니다. CPU 설정으로 실행하세요.")
        self.device = torch.device(requested_device)
        torch.set_num_threads(max(1, int(os.environ.get("SCALP_THREADS", min(4, os.cpu_count() or 1)))))
        self.models: dict[str, nn.Module] = {}
        self.transforms = {}
        self.status = "loading"
        self.error = None
        self.configuration_id = None
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()

    def _find_model_dir(self) -> Path:
        configured = os.environ.get("SCALP_MODEL_DIR")
        if configured:
            return Path(configured).expanduser().resolve()
        local = BASE_DIR / "models"
        if all((local / c["filename"]).is_file() for c in self.configs):
            return local
        return Path.home() / "Downloads" / "scalp_4indicator_models"

    def _model_path(self, config: dict) -> Path:
        configured = self.model_dir / config["filename"]
        if configured.is_file() or self._explicit_model_dir:
            return configured
        bundled = config.get("bundled_path")
        if bundled:
            return BASE_DIR / bundled
        return configured

    def start_loading(self):
        threading.Thread(target=self.load, name="model-loader", daemon=True).start()

    def load(self):
        with self._load_lock:
            if self.status == "ready":
                return
            try:
                missing = [c["filename"] for c in self.configs if not self._model_path(c).is_file()]
                if missing:
                    raise FileNotFoundError("모델 파일을 찾을 수 없습니다: " + ", ".join(missing))
                signature = hashlib.sha256(json.dumps(self.configs, sort_keys=True).encode())
                for c in self.configs:
                    path = self._model_path(c)
                    checkpoint = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
                    if not isinstance(checkpoint, dict) or not all(isinstance(v, torch.Tensor) for v in checkpoint.values()):
                        raise ValueError(f"{c['id']}: 순수 state_dict 형식이 아닙니다.")
                    if c.get("classifier") == "sebum_attention_fusion":
                        # Use the supplied, unchanged inference module. It retains
                        # the learned block norms, attention pools and auxiliary head4.
                        from model_packages.sebum.predict import ScalpNet
                        model = ScalpNet()
                    elif c["architecture"] == "efficientnet_b4":
                        model = models.efficientnet_b4(weights=None, num_classes=c["num_classes"])
                    else:
                        model = DinoClassifier(c)
                    # No missing keys, silent random layers, or downloaded base weights.
                    model.load_state_dict(checkpoint, strict=True)
                    del checkpoint
                    model.requires_grad_(False).eval().to(self.device)
                    self.models[c["id"]] = model
                    self.transforms[c["id"]] = build_transform(c)
                    # Stream the file to keep provenance stable across model replacements.
                    weights_digest = hashlib.sha256()
                    with path.open("rb") as source:
                        while block := source.read(1024 * 1024):
                            signature.update(block)
                            weights_digest.update(block)
                    if c.get("expected_sha256") and weights_digest.hexdigest() != c["expected_sha256"]:
                        raise ValueError(f"{c['name']}: 학습 코드와 대조한 가중치 파일과 일치하지 않습니다.")
                self.configuration_id = signature.hexdigest()[:24]
                self.status = "ready"
            except Exception as exc:
                self.models.clear()
                self.transforms.clear()
                self.error = str(exc)
                self.status = "error"
                import logging
                logging.exception("Model loading failed")

    def health(self) -> dict:
        return {
            "status": self.status, "device": str(self.device),
            "message": {"loading": "4개 모델을 불러오는 중입니다.", "ready": "4개 모델이 연결되었습니다.",
                        "error": "모델을 불러오지 못했습니다. 서버 로그와 모델 경로를 확인하세요."}[self.status],
            "settings_verified": all(c.get("settings_verified") is True for c in self.configs),
            "labels_confirmed": all(c.get("labels_confirmed") is True for c in self.configs),
            "configuration_id": self.configuration_id,
            "models": [{"id": c["id"], "name": c["name"], "ready": c["id"] in self.models,
                        "num_classes": c["num_classes"], "labels": self._labels(c),
                        "labels_confirmed": c.get("labels_confirmed") is True,
                        "excluded_classes": c.get("excluded_classes", []),
                        "grade_indices": c.get("grade_indices"),
                        "grading_method": c.get("grading_method", "argmax"),
                        "grade_labels": c.get("grade_labels", list(GRADE_LABELS)),
                        "preprocessing_version": c.get("preprocessing_version"),
                        "settings_verified": c.get("settings_verified") is True} for c in self.configs],
        }

    @staticmethod
    def _labels(config):
        # User-confirmed label meanings are independent of preprocessing verification.
        if config.get("labels_confirmed") is True or config.get("settings_verified") is True:
            return config["labels"]
        return [f"클래스 {i}" for i in range(config["num_classes"])]

    def _metric(self, config, probabilities):
        values = [float(v) for v in probabilities]
        excluded = config.get("excluded_classes", [])
        candidates = [i for i in range(len(values)) if i not in excluded]
        if not candidates:
            raise ValueError("최종 판정에 사용할 클래스가 없습니다.")
        index = max(candidates, key=values.__getitem__)
        labels = self._labels(config)
        grades = config.get("grade_indices")
        method = config.get("grading_method", "argmax")
        confirmed = config.get("labels_confirmed") is True or config.get("settings_verified") is True
        grade_labels = config.get("grade_labels", list(GRADE_LABELS))
        grade_probabilities = None
        grade_index = None
        if confirmed and grades is not None:
            grade_probabilities = [0.0] * len(grade_labels)
            for raw_index in candidates:
                if grades[raw_index] is not None:
                    grade_probabilities[grades[raw_index]] += values[raw_index]
            if method == "probability_merge":
                # Sum mapped probabilities before selecting the final label (three grades or binary presence).
                grade_index = max(range(len(grade_probabilities)), key=grade_probabilities.__getitem__)
            else:
                grade_index = grades[index]
        return {"id": config["id"], "name": config["name"], "class_index": index,
                "label": grade_labels[grade_index] if grade_index is not None else labels[index],
                "confidence": values[index], "probabilities": values,
                "class_labels": labels, "settings_verified": config.get("settings_verified") is True,
                "labels_confirmed": config.get("labels_confirmed") is True,
                "grade_index": grade_index, "grade_probabilities": grade_probabilities,
                "grade_labels": list(grade_labels) if confirmed else None,
                "grade_confidence": grade_probabilities[grade_index] if grade_index is not None else None,
                "grade_indices": list(grades) if grades is not None else None,
                "grading_method": method,
                "excluded_classes": list(excluded),
                "preprocessing_version": config.get("preprocessing_version")}

    def analyze(self, images: list[Image.Image]) -> dict:
        if self.status != "ready":
            raise ModelUnavailable(self.health()["message"])
        if not self._lock.acquire(blocking=False):
            raise AnalysisBusy("다른 사진을 분석 중입니다. 잠시 후 다시 시도하세요.")
        started = time.perf_counter()
        try:
            per_photo = [{"index": i, "metrics": []} for i in range(len(images))]
            metrics = []
            with torch.inference_mode():
                for c in self.configs:
                    # Process one image at a time to bound CPU memory use.
                    outputs = []
                    for i, image in enumerate(images):
                        tensor = self.transforms[c["id"]](image).unsqueeze(0).to(self.device)
                        logits = self.models[c["id"]](tensor)
                        if logits.shape != (1, c["num_classes"]) or not torch.isfinite(logits).all():
                            raise RuntimeError("모델 출력이 올바르지 않습니다.")
                        probabilities = logits.softmax(dim=-1)[0].cpu()
                        outputs.append(probabilities)
                        per_photo[i]["metrics"].append(self._metric(c, probabilities))
                    metrics.append(self._metric(c, torch.stack(outputs).mean(dim=0)))
            verified = all(c.get("settings_verified") is True for c in self.configs)
            unverified = [c["name"] for c in self.configs if c.get("settings_verified") is not True]
            return {
                "id": str(uuid4()), "date": datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
                "source": "model", "photo_count": len(images), "aggregation": "mean_probabilities",
                "settings_verified": verified,
                "warnings": [] if verified else [", ".join(unverified) + ": " + UNVERIFIED_WARNING],
                "metrics": metrics, "per_photo": per_photo,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "configuration_id": self.configuration_id,
            }
        finally:
            self._lock.release()
