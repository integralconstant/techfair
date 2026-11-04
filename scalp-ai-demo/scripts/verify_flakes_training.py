"""Compare the web adapter with the supplied training/evaluation definitions.

Runs one unchanged checkpoint on three supplied test photos. Does not run the
training/evaluation entry points or write into the supplied training directory.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import timm
import torch
from PIL import Image
from torch import nn
from torchvision import transforms
from torchvision.transforms import InterpolationMode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inference import DinoClassifier, ModelService, build_transform, read_config


def constant(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing reference constant: {name}")


def file_sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-dir", type=Path, default=Path.home() / "Downloads" / "각질량 코드")
    args = parser.parse_args()
    training = args.training_dir.resolve()
    config = read_config(ROOT / "model_config.json")[0]
    # The original web checkpoint was proved byte-identical to this supplied file.
    checkpoint = training / "best_models" / "seed42_fold0.pth"
    assert file_sha(checkpoint) == config["expected_sha256"], "Reference checkpoint changed"
    model_dir = ModelService().model_dir
    assert file_sha(model_dir / config["filename"]) == config["expected_sha256"], "Web checkpoint changed"

    train_path, eval_path = training / "train.py", training / "test_eval.py"
    train_tree = ast.parse(train_path.read_text(encoding="utf-8-sig"))
    eval_tree = ast.parse(eval_path.read_text(encoding="utf-8-sig"))
    namespace = {"torch": torch, "nn": nn, "timm": timm, "np": np,
                 "transforms": transforms, "InterpolationMode": InterpolationMode}
    for name in ("IMAGENET_MEAN", "IMAGENET_STD"):
        namespace[name] = constant(train_tree, name)
    namespace["IMG_SIZE"] = constant(eval_tree, "IMG_SIZE")
    namespace["MERGE_MAP"] = constant(eval_tree, "MERGE_MAP")
    model_class = next(node for node in train_tree.body if isinstance(node, ast.ClassDef) and node.name == "ScalpClassifier")
    merge_function = next(node for node in eval_tree.body if isinstance(node, ast.FunctionDef) and node.name == "merge_to_3")
    # Compile only the reviewed class and probability merge helper, not either main().
    exec(compile(ast.Module(body=[model_class], type_ignores=[]), str(train_path), "exec"), namespace)
    exec(compile(ast.Module(body=[merge_function], type_ignores=[]), str(eval_path), "exec"), namespace)
    evaluation_main = next(node for node in eval_tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    transform_assignment = next(node for node in evaluation_main.body if isinstance(node, ast.Assign)
                                and any(isinstance(target, ast.Name) and target.id == "transform" for target in node.targets))
    reference_transform = eval(compile(ast.Expression(transform_assignment.value), str(eval_path), "eval"), namespace)
    web_transform = build_transform(config)

    torch.set_num_threads(4)
    reference = namespace["ScalpClassifier"](constant(eval_tree, "BACKBONE"), 4, namespace["IMG_SIZE"], 0.3, pretrained=False)
    adapted = DinoClassifier(config)
    weights = torch.load(checkpoint, weights_only=True, map_location="cpu", mmap=True)
    reference.load_state_dict(weights, strict=True)
    adapted.load_state_dict(weights, strict=True)
    del weights
    reference.requires_grad_(False).eval()
    adapted.requires_grad_(False).eval()
    service = ModelService.__new__(ModelService)
    cases = []
    with torch.inference_mode():
        for folder in ("0_normal", "1_mild_moderate", "2_severe"):
            photo = next(iter(sorted((training / "data" / "test" / folder).glob("*.jpg"))))
            with Image.open(photo) as image:
                rgb = image.convert("RGB")
            expected_tensor = reference_transform(rgb).unsqueeze(0)
            actual_tensor = web_transform(rgb).unsqueeze(0)
            torch.testing.assert_close(actual_tensor, expected_tensor, rtol=0, atol=0)
            expected_logits = reference(expected_tensor)
            actual_logits = adapted(actual_tensor)
            torch.testing.assert_close(actual_logits, expected_logits, rtol=1e-6, atol=1e-6)
            p4 = expected_logits.float().softmax(dim=1).cpu().numpy()
            expected_p3 = namespace["merge_to_3"](p4)[0]
            actual = service._metric(config, actual_logits.float().softmax(dim=1)[0])
            np.testing.assert_allclose(actual["grade_probabilities"], expected_p3, rtol=1e-6, atol=1e-7)
            assert actual["grade_index"] == int(expected_p3.argmax())
            assert actual["class_index"] == int(p4[0].argmax())
            cases.append({"photo": photo.name, "grade": actual["label"],
                          "max_logit_error": (actual_logits - expected_logits).abs().max().item()})
            rgb.close()
    print(json.dumps({"result": "PASS", "checkpoint_sha256": config["expected_sha256"],
                      "reference_input_size": namespace["IMG_SIZE"], "cases": cases,
                      "scope": "single checkpoint parity with supplied source, not ensemble accuracy"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
