"""Compare the real web sebum adapter with the unchanged supplied package.

Reads the original ZIP and local test photos without changing either. Loads the
actual web models and the package's CPU predictor, then compares preprocessing,
weights, logits, merged probabilities and final labels. This is an integration
parity check, not an accuracy evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
import zipfile
from pathlib import Path

import timm
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inference import ModelService, build_transform

EXPECTED_SHA256 = "d5519a5f3c0c21c25cf18d312f41b72a2ef67a3db556605b0f8d79314f4319d0"
PREPROCESSING_VERSION = "sebum-384-attention-v1"
PACKAGE = ROOT / "model_packages" / "sebum"


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_package(archive):
    with zipfile.ZipFile(archive) as supplied:
        prediction = next(name for name in supplied.namelist()
                          if name.endswith("/\ud53c\uc9c0/predict.py"))
        prefix = prediction.rsplit("/", 1)[0] + "/"
        for name in ("predict.py", "requirements.txt", "INTEGRATION.md"):
            assert (PACKAGE / name).read_bytes() == supplied.read(prefix + name), (
                "Packaged source differs from the supplied ZIP: " + name
            )
        with supplied.open(prefix + "weights/sebum_fold0.pth") as stream:
            archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    checkpoint = PACKAGE / "weights" / "sebum_fold0.pth"
    assert archive_sha == EXPECTED_SHA256, "The supplied checkpoint changed"
    assert file_sha(checkpoint) == EXPECTED_SHA256, "The packaged checkpoint changed"
    return checkpoint


def synthetic_image(width, height, variant=0):
    pixels = bytes(channel for y in range(height) for x in range(width)
                   for channel in ((x + variant * 53) % 256,
                                   (y * 2 + variant * 29) % 256,
                                   (x + y + variant * 97) % 256))
    return Image.frombytes("RGB", (width, height), pixels)


def sample_cases(training_dir):
    cases = [("synthetic-640x480", "synthetic", synthetic_image(640, 480))]
    folders = ("0_normal", "1_mild_moderate")
    for index, folder in enumerate(folders, 1):
        candidates = sorted((training_dir / "data" / "test" / folder).glob("*.jpg"))
        if candidates:
            path = candidates[0]
            with Image.open(path) as image:
                rgb = image.convert("RGB")
            cases.append((path.name, "supplied_sample", rgb))
        else:
            width, height = ((480, 640), (320, 280))[index - 1]
            cases.append((f"synthetic-{width}x{height}", "synthetic",
                          synthetic_image(width, height, index)))
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path,
                        default=Path.home() / "Downloads" / "\uac01\uc9c8, \ud53c\uc9c0.zip")
    parser.add_argument("--training-dir", type=Path,
                        default=Path.home() / "Downloads" / "\uac01\uc9c8\ub7c9 \ucf54\ub4dc")
    args = parser.parse_args()
    checkpoint = verify_package(args.archive)
    assert timm.__version__ == "1.0.28", "Install the package's pinned timm==1.0.28 first"
    provider = importlib.import_module("model_packages.sebum.predict")
    assert Path(provider.__file__).resolve() == (PACKAGE / "predict.py").resolve()

    # Keep both paths on CPU so this checks the same numerical execution mode.
    os.environ["SCALP_DEVICE"] = "cpu"
    torch.set_num_threads(4)
    service = ModelService()
    config = next(item for item in service.configs if item["id"] == "sebum")
    assert config["expected_sha256"] == EXPECTED_SHA256
    assert config["preprocessing_version"] == PREPROCESSING_VERSION
    assert config["grade_indices"] == [0, 1, 1]
    assert config["grade_labels"] == provider.GRADES
    assert config["grading_method"] == "probability_merge"
    assert config["input_size"] == config["resize_size"] == provider.IMG_SIZE == 384
    assert config.get("resize_mode") == "squash"
    service.load()
    assert service.status == "ready", service.error
    adapted = service.models["sebum"]
    assert isinstance(adapted, provider.ScalpNet), "The web must use the supplied model class"
    assert hasattr(adapted, "head4"), "The strict checkpoint includes the auxiliary head"
    native = provider.ScalpPredictor(weights=[checkpoint], device="cpu")
    native_model = native.models[0]
    actual_state, expected_state = adapted.state_dict(), native_model.state_dict()
    assert actual_state.keys() == expected_state.keys(), "Loaded tensor keys differ"
    for name in actual_state:
        assert torch.equal(actual_state[name], expected_state[name]), "Loaded weight differs: " + name
    del actual_state, expected_state

    # The raw winning class can be normal while the combined presence wins.
    merge_fixture = torch.tensor([0.40, 0.35, 0.25])
    expected_merge = provider.merge_to_2(merge_fixture)
    fixture = service._metric(config, merge_fixture)
    torch.testing.assert_close(torch.tensor(fixture["grade_probabilities"]), expected_merge)
    assert fixture["class_index"] == 0 and fixture["grade_index"] == 1
    assert fixture["label"] == provider.GRADES[1]
    tie_fixture = service._metric(config, [0.50, 0.25, 0.25])
    assert tie_fixture["grade_index"] == 0, "Equal binary probabilities use the first grade"

    web_transform = build_transform(config)
    samples = sample_cases(args.training_dir)
    cases = []
    try:
        with torch.inference_mode():
            for name, kind, image in samples:
                expected_tensor = native.transform(image).unsqueeze(0)
                actual_tensor = web_transform(image).unsqueeze(0)
                torch.testing.assert_close(actual_tensor, expected_tensor, rtol=0, atol=0)
                expected_logits = native_model(expected_tensor)
                actual_logits = adapted(actual_tensor)
                torch.testing.assert_close(actual_logits, expected_logits, rtol=0, atol=0)
                raw = actual_logits.float().softmax(dim=1)[0]
                expected_binary = provider.merge_to_2(raw)
                metric = service._metric(config, raw)
                torch.testing.assert_close(torch.tensor(metric["grade_probabilities"]),
                                           expected_binary.cpu(), rtol=1e-6, atol=1e-7)
                assert metric["class_index"] == int(raw.argmax())
                assert metric["grade_index"] == int(expected_binary.argmax())
                result = native.predict(image)
                assert metric["label"] == result["grade"]
                assert abs(metric["grade_confidence"] - result["confidence"]) <= 0.000051
                for label, value in zip(provider.GRADES, metric["grade_probabilities"]):
                    assert abs(value - result["probs"][label]) <= 0.000051
                cases.append({"image": name, "kind": kind, "grade": metric["label"],
                              "max_logit_error": (actual_logits - expected_logits).abs().max().item()})
    finally:
        for _, _, image in samples:
            image.close()
    print(json.dumps({
        "result": "PASS", "checkpoint_sha256": EXPECTED_SHA256,
        "timm_version": timm.__version__, "input_size": provider.IMG_SIZE,
        "source_bytes_match": True, "loaded_weights_match": True,
        "raw_argmax_differs_from_binary_fixture": True, "cases": cases,
        "scope": "CPU single-checkpoint parity with unchanged supplied package; not model accuracy",
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
