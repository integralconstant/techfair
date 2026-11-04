"""Exercise upload boundaries and inference semantics without real model weights.

Run: .venv\\Scripts\\python.exe -m unittest discover -s tests -v
Real checkpoint loading and browser integration are checked separately.
"""

from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import torch
from flask import request
from PIL import Image
from torch import nn
from torchvision import transforms
from torchvision.transforms import InterpolationMode

import inference
import server
from inference import AnalysisBusy, ModelService, ModelUnavailable, read_config


def photo_bytes(mode="RGB", image_format="PNG", size=(8, 6), **save_options):
    stream = io.BytesIO()
    with Image.new(mode, size, color=128 if mode == "L" else (32, 64, 96)) as image:
        image.save(stream, format=image_format, **save_options)
    stream.seek(0)
    return stream


class RecordingService:
    def __init__(self):
        self.images = []
        self.observed = []
        self.streams_in_memory = False
        self.failure = None

    def health(self):
        return {"status": "ready", "models": [], "device": "cpu"}

    def analyze(self, images):
        self.images = list(images)
        self.observed = [(image.mode, image.size) for image in images]
        self.streams_in_memory = all(
            isinstance(upload.stream, io.BytesIO)
            for upload in request.files.getlist("photos")
        )
        if self.failure:
            raise self.failure
        return {"source": "model", "photo_count": len(images)}


class UploadApiTests(unittest.TestCase):
    def setUp(self):
        self.service = RecordingService()
        temporary_database = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_database.cleanup)
        self.app = server.create_app(self.service, database_path=Path(temporary_database.name) / "test.sqlite3")
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def upload(self, photos=None, **kwargs):
        return self.client.post(
            "/api/analyze", data={"photos": photos or []},
            content_type="multipart/form-data", **kwargs,
        )

    def assert_error(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertIsInstance(response.json["error"], str)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_site_and_health_are_served_without_loading_real_models(self):
        site = self.client.get("/")
        self.assertEqual(site.status_code, 200)
        self.assertIn(b'<html lang="ko">', site.data)
        site.close()
        health = self.client.get("/api/health")
        self.assertEqual(health.json["status"], "ready")
        self.assertEqual(health.json["application"], "scalp-ai-demo")
        self.assertEqual(health.json["installation_id"], server.installation_id(server.BASE_DIR))
        self.assertNotIn(str(server.BASE_DIR), health.get_data(as_text=True))
        self.assertEqual(health.headers["Cache-Control"], "no-store")

    def test_one_grayscale_image_is_rgb_and_never_spooled_to_disk(self):
        response = self.upload([(photo_bytes(mode="L"), "scalp.png")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["photo_count"], 1)
        self.assertEqual(self.service.observed, [("RGB", (8, 6))])
        self.assertTrue(self.service.streams_in_memory)
        with self.assertRaises(ValueError):
            self.service.images[0].getpixel((0, 0))

    def test_three_jpeg_png_webp_images_reach_the_service(self):
        response = self.upload([
            (photo_bytes(image_format=fmt), f"scalp.{fmt.lower()}")
            for fmt in ("JPEG", "PNG", "WEBP")
        ])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["photo_count"], 3)
        self.assertTrue(all(mode == "RGB" for mode, _ in self.service.observed))

    def test_exif_orientation_is_applied_before_inference(self):
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90 degrees clockwise.
        response = self.upload([
            (photo_bytes(image_format="JPEG", size=(8, 6), exif=exif), "scalp.jpg")
        ])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.observed, [("RGB", (6, 8))])

    def test_missing_or_four_photos_are_rejected(self):
        for count in (0, 4):
            with self.subTest(count=count):
                response = self.upload([(photo_bytes(), f"{i}.png") for i in range(count)])
                self.assert_error(response, 400)
        self.assertFalse(self.service.images)

    def test_unexpected_multipart_file_field_is_rejected(self):
        response = self.client.post("/api/analyze", data={
            "photos": (photo_bytes(), "scalp.png"),
            "other": (photo_bytes(), "unexpected.png"),
        })
        self.assert_error(response, 400)

    def test_svg_gif_and_corrupt_photo_are_rejected_by_decoding(self):
        payloads = [
            (io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg"/>'), "scalp.png"),
            (photo_bytes(image_format="GIF"), "scalp.png"),
            (io.BytesIO(b"not a photo"), "scalp.jpg"),
        ]
        for payload, filename in payloads:
            with self.subTest(filename=filename, payload=payload.getvalue()[:8]):
                self.assert_error(self.upload([(payload, filename)]), 400)
        self.assertFalse(self.service.images)

    def test_per_file_limit_and_total_request_limit_are_enforced(self):
        with patch.object(server, "MAX_FILE_BYTES", 32):
            self.assert_error(self.upload([(io.BytesIO(b"x" * 33), "large.jpg")]), 400)
        self.app.config["MAX_CONTENT_LENGTH"] = 256
        self.assert_error(self.upload([(io.BytesIO(b"x" * 1024), "large.jpg")]), 413)

    def test_pixel_limit_is_enforced_before_conversion(self):
        with patch.object(server, "MAX_PIXELS", 16):
            self.assert_error(self.upload([(photo_bytes(size=(8, 6)), "large.png")]), 400)

    def test_same_origin_is_allowed_but_cross_origin_is_rejected(self):
        response = self.upload([(photo_bytes(), "scalp.png")], headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 200)
        self.assert_error(self.upload(
            [(photo_bytes(), "scalp.png")], headers={"Origin": "https://unrelated.example"},
        ), 403)

    def test_unavailable_busy_and_failed_inference_never_return_fake_success(self):
        for failure, status in [
            (ModelUnavailable("models loading"), 503),
            (AnalysisBusy("already analyzing"), 429),
            (RuntimeError("private/local/path"), 500),
        ]:
            with self.subTest(status=status):
                self.service.failure = failure
                if status == 500:
                    with self.assertLogs(self.app.logger, level="ERROR"):
                        response = self.upload([(photo_bytes(), "scalp.png")])
                    self.assertNotIn("private/local/path", response.get_data(as_text=True))
                else:
                    response = self.upload([(photo_bytes(), "scalp.png")])
                self.assert_error(response, status)
                with self.assertRaises(ValueError):
                    self.service.images[0].getpixel((0, 0))

    def test_api_not_found_and_wrong_method_are_json_errors(self):
        self.assert_error(self.client.get("/api/not-found"), 404)
        self.assert_error(self.client.put("/api/analyze"), 405)


class SequenceModel(nn.Module):
    def __init__(self, probabilities):
        super().__init__()
        self.outputs = [torch.tensor(row, dtype=torch.float32).log().unsqueeze(0) for row in probabilities]
        self.index = 0

    def forward(self, _):
        output = self.outputs[self.index]
        self.index += 1
        return output


def simulated_service(photo_count=3):
    service = ModelService.__new__(ModelService)
    service.configs = read_config(server.BASE_DIR / "model_config.json")
    service.status = "ready"
    service.device = torch.device("cpu")
    service.configuration_id = "test-configuration"
    service._lock = threading.Lock()
    service.models = {}
    service.transforms = {}
    for config in service.configs:
        rows = [[0.8, 0.1, 0.1], [0.2, 0.7, 0.1], [0.2, 0.2, 0.6]]
        if config["num_classes"] == 4:
            rows = [[0.7, 0.15, 0.1, 0.05], [0.2, 0.6, 0.1, 0.1], [0.2, 0.15, 0.55, 0.1]]
        service.models[config["id"]] = SequenceModel(rows[:photo_count])
        service.transforms[config["id"]] = lambda _: torch.zeros(3, 4, 4)
    return service


class AggregationTests(unittest.TestCase):
    def test_three_photos_use_mean_probabilities_and_keep_all_individual_outputs(self):
        service = simulated_service()
        result = service.analyze([object(), object(), object()])
        self.assertEqual(result["aggregation"], "mean_probabilities")
        self.assertEqual([m["id"] for m in result["metrics"]], [c["id"] for c in service.configs])
        self.assertEqual([p["index"] for p in result["per_photo"]], [0, 1, 2])
        for metric in result["metrics"]:
            expected = [1.1 / 3, 0.9 / 3, 0.75 / 3, 0.25 / 3] if metric["id"] == "flakes" else [0.4, 1 / 3, 0.8 / 3]
            torch.testing.assert_close(torch.tensor(metric["probabilities"]), torch.tensor(expected))
            self.assertEqual(metric["class_index"], 0)
            self.assertEqual(metric["grade_index"], 1 if metric["id"] in {"flakes", "sebum"} else 0)
            self.assertEqual(metric["label"], {"flakes": "경중등도", "sebum": "유"}.get(metric["id"], "정상"))
            expected_grades = ([1.1 / 3, 1.65 / 3, 0.25 / 3] if metric["id"] == "flakes"
                               else [0.4, 0.6] if metric["id"] == "sebum" else expected)
            torch.testing.assert_close(torch.tensor(metric["grade_probabilities"]), torch.tensor(expected_grades))
            self.assertTrue(metric["labels_confirmed"])
            self.assertAlmostEqual(sum(metric["probabilities"]), 1, places=6)
        for photo, expected_indices in zip(result["per_photo"], ([0, 0, 0, 0], [1, 1, 1, 1], [2, 2, 2, 2])):
            self.assertEqual([m["class_index"] for m in photo["metrics"]], expected_indices)
        self.assertEqual([p["metrics"][0]["grade_index"] for p in result["per_photo"]], [0, 1, 1])
        self.assertEqual([p["metrics"][1]["grade_index"] for p in result["per_photo"]], [0, 1, 1])
        self.assertFalse(result["settings_verified"])
        self.assertTrue(result["warnings"])
        self.assertEqual(result["configuration_id"], "test-configuration")

    def test_single_photo_matches_aggregate_and_unverified_labels_remain_neutral(self):
        service = simulated_service(photo_count=1)
        for config in service.configs:
            config["labels"] = ["medical-label"] * config["num_classes"]
            config["labels_confirmed"] = False
            config["settings_verified"] = False
        result = service.analyze([object()])
        self.assertEqual(result["metrics"], result["per_photo"][0]["metrics"])
        for metric in result["metrics"]:
            self.assertEqual(metric["label"], f"클래스 {metric['class_index']}")
            self.assertNotIn("medical-label", metric["class_labels"])
            self.assertIsNone(metric["grade_index"])

    def test_busy_lock_prevents_parallel_inference(self):
        service = simulated_service(photo_count=1)
        with service._lock:
            with self.assertRaises(AnalysisBusy):
                service.analyze([object()])
        self.assertEqual(service.models["flakes"].index, 0)

    def test_invalid_output_shape_or_nan_fails_and_releases_lock(self):
        for output in (torch.full((1, 4), float("nan")), torch.zeros(1, 3)):
            with self.subTest(shape=tuple(output.shape)):
                service = simulated_service(photo_count=1)
                service.models["flakes"].outputs = [output]
                with self.assertRaisesRegex(RuntimeError, "모델 출력"):
                    service.analyze([object()])
                self.assertTrue(service._lock.acquire(blocking=False))
                service._lock.release()


class GradeMappingTests(unittest.TestCase):
    def setUp(self):
        self.service = simulated_service(photo_count=1)
        self.configs = {config["id"]: config for config in self.service.configs}

    def test_flakes_class_zero_is_restored_as_normal(self):
        probabilities = [0.85, 0.03, 0.09, 0.03]
        result = self.service._metric(self.configs["flakes"], probabilities)
        self.assertEqual(result["class_index"], 0)
        self.assertEqual(result["grade_index"], 0)
        self.assertEqual(result["label"], "정상")
        self.assertEqual(result["excluded_classes"], [])
        self.assertEqual(result["confidence"], 0.85)
        self.assertEqual(result["probabilities"], probabilities)
        self.assertEqual(result["grade_probabilities"], [0.85, 0.12, 0.03])
        self.assertAlmostEqual(sum(result["probabilities"]), 1)

    def test_flakes_adds_mild_and_moderate_probabilities_before_argmax(self):
        probabilities = [0.010, 0.307, 0.336, 0.347]
        result = self.service._metric(self.configs["flakes"], probabilities)
        self.assertEqual(result["class_index"], 3)
        self.assertAlmostEqual(result["confidence"], 0.347)
        self.assertEqual(result["grade_index"], 1)
        self.assertEqual(result["label"], "경중등도")
        torch.testing.assert_close(torch.tensor(result["grade_probabilities"]), torch.tensor([0.010, 0.643, 0.347]))
        self.assertAlmostEqual(result["grade_confidence"], 0.643)
        self.assertEqual(result["grading_method"], "probability_merge")

    def test_each_flakes_final_grade_uses_the_training_merge_rule(self):
        cases = [([0.7, 0.1, 0.1, 0.1], 0, "정상"),
                 ([0.4, 0.3, 0.25, 0.05], 1, "경중등도"),
                 ([0.1, 0.1, 0.1, 0.7], 2, "중증")]
        for probabilities, grade, label in cases:
            with self.subTest(grade=grade):
                result = self.service._metric(self.configs["flakes"], probabilities)
                self.assertEqual(result["class_index"], max(range(4), key=probabilities.__getitem__))
                self.assertEqual(result["grade_index"], grade)
                self.assertEqual(result["label"], label)
                self.assertTrue(result["labels_confirmed"])
                self.assertTrue(result["settings_verified"])
                self.assertEqual(result["preprocessing_version"], "flakes-384-square-v1")

    def test_other_models_select_the_highest_probability_instead_of_the_highest_class_number(self):
        for model_id in ("hair_loss", "erythema"):
            for selected, label in enumerate(("정상", "경증", "중증")):
                with self.subTest(model=model_id, selected=selected):
                    probabilities = [0.1, 0.1, 0.1]
                    probabilities[selected] = 0.8
                    result = self.service._metric(self.configs[model_id], probabilities)
                    self.assertEqual(result["class_index"], selected)
                    self.assertEqual(result["grade_index"], selected)
                    self.assertEqual(result["label"], label)
                    self.assertEqual(result["excluded_classes"], [])
                    self.assertEqual(result["grade_probabilities"], probabilities)
                    self.assertEqual(result["grading_method"], "argmax")

    def test_flakes_and_sebum_are_verified_while_other_two_remain_unverified(self):
        result = self.service.analyze([object()])
        self.assertFalse(result["settings_verified"])
        self.assertTrue(result["warnings"])
        self.assertIn("탈모", " ".join(result["warnings"]))
        self.assertIn("모낭사이홍반", " ".join(result["warnings"]))
        self.assertNotIn("피지", " ".join(result["warnings"]))
        for metric in result["metrics"]:
            self.assertTrue(metric["labels_confirmed"])
            self.assertEqual(metric["settings_verified"], metric["id"] in {"flakes", "sebum"})
            self.assertIn(metric["label"], metric["grade_labels"])

    def test_sebum_sums_present_probabilities_before_deciding_binary_presence(self):
        for probabilities, expected_grade, expected_label in [
            ([0.4, 0.35, 0.25], 1, "유"),
            ([0.75, 0.15, 0.1], 0, "무"),
            ([0.2, 0.1, 0.7], 1, "유"),
            ([0.5, 0.25, 0.25], 0, "무"),
        ]:
            with self.subTest(probabilities=probabilities):
                metric = self.service._metric(self.configs["sebum"], probabilities)
                self.assertEqual(metric["class_index"], max(range(3), key=probabilities.__getitem__))
                self.assertEqual(metric["grade_index"], expected_grade)
                self.assertEqual(metric["label"], expected_label)
                self.assertEqual(metric["grade_labels"], ["무", "유"])
                self.assertEqual(metric["grade_indices"], [0, 1, 1])
                torch.testing.assert_close(torch.tensor(metric["grade_probabilities"]),
                                           torch.tensor([probabilities[0], probabilities[1] + probabilities[2]]))
                self.assertEqual(metric["confidence"], probabilities[metric["class_index"]])
                self.assertEqual(metric["grade_confidence"], metric["grade_probabilities"][expected_grade])
                self.assertEqual(metric["grading_method"], "probability_merge")
                self.assertEqual(metric["preprocessing_version"], "sebum-384-attention-v1")
                self.assertTrue(metric["settings_verified"])

    def test_binary_grade_configuration_rejects_indices_outside_its_two_labels(self):
        configs = deepcopy(self.service.configs)
        configs[1]["grade_indices"] = [0, 1, 2]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-binary.json"
            path.write_text(json.dumps({"models": configs}), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_config(path)

    def test_invalid_excluded_classes_are_rejected_in_configuration(self):
        for excluded in ([True], [-1], [4], [0, 0], [0, 1, 2, 3], "0"):
            with self.subTest(excluded=excluded):
                configs = deepcopy(self.service.configs)
                configs[0]["excluded_classes"] = excluded
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "invalid.json"
                    path.write_text(json.dumps({"models": configs}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        read_config(path)

    def test_confirmed_grade_mapping_requires_an_eligible_grade_for_each_class(self):
        for grade_indices in ([None, 0, 1], [None, 0, 1, True], [None, 0, 1, 3], [None, None, 1, 2]):
            with self.subTest(grade_indices=grade_indices):
                configs = deepcopy(self.service.configs)
                configs[0]["grade_indices"] = grade_indices
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "invalid.json"
                    path.write_text(json.dumps({"models": configs}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        read_config(path)

    def test_merge_cannot_drop_classes_or_use_an_unknown_grading_method(self):
        for change in ({"excluded_classes": [0]}, {"grading_method": "highest_class_number"},
                       {"grade_labels": ["정상", "중증"]}):
            with self.subTest(change=change):
                configs = deepcopy(self.service.configs)
                configs[0].update(change)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "invalid.json"
                    path.write_text(json.dumps({"models": configs}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        read_config(path)


class PreprocessingTests(unittest.TestCase):
    def setUp(self):
        self.configs = read_config(server.BASE_DIR / "model_config.json")
        self.image = Image.new("RGB", (640, 360))
        self.image.putdata([((x * 3) % 256, (y * 5) % 256, (x + y) % 256)
                            for y in range(self.image.height) for x in range(self.image.width)])

    def tearDown(self):
        self.image.close()

    def test_flakes_matches_training_square_resize_without_center_crop(self):
        config = self.configs[0]
        reference = transforms.Compose([
            transforms.Resize((384, 384), interpolation=InterpolationMode.BICUBIC),
            transforms.ToTensor(), transforms.Normalize(config["mean"], config["std"]),
        ])
        actual = inference.build_transform(config)(self.image)
        self.assertEqual(tuple(actual.shape), (3, 384, 384))
        torch.testing.assert_close(actual, reference(self.image), rtol=0, atol=0)
        previous_crop = transforms.Compose([
            transforms.Resize(384, interpolation=InterpolationMode.BICUBIC),
            transforms.CenterCrop(384), transforms.ToTensor(),
            transforms.Normalize(config["mean"], config["std"]),
        ])
        self.assertFalse(torch.equal(actual, previous_crop(self.image)))

    def test_sebum_matches_package_square_resize_on_a_rectangular_photo(self):
        config = self.configs[1]
        self.assertEqual(config["input_size"], 384)
        self.assertEqual(config["resize_mode"], "squash")
        reference = transforms.Compose([
            transforms.Resize((384, 384), interpolation=InterpolationMode.BICUBIC),
            transforms.ToTensor(), transforms.Normalize(config["mean"], config["std"]),
        ])
        actual = inference.build_transform(config)(self.image)
        self.assertEqual(tuple(actual.shape), (3, 384, 384))
        torch.testing.assert_close(actual, reference(self.image), rtol=0, atol=0)

    def test_other_two_models_retain_their_previous_resize_and_crop(self):
        for config in self.configs[2:]:
            with self.subTest(model=config["id"]):
                reference = transforms.Compose([
                    transforms.Resize(config["resize_size"], interpolation=InterpolationMode(config["interpolation"])),
                    transforms.CenterCrop(config["input_size"]), transforms.ToTensor(),
                    transforms.Normalize(config["mean"], config["std"]),
                ])
                torch.testing.assert_close(inference.build_transform(config)(self.image),
                                           reference(self.image), rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
