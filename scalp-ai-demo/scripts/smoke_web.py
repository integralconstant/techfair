"""Exercise the guided photo flow against the running, real four-model API.

Synthetic patterns exercise integration only; they do not measure scalp accuracy.
"""

import argparse
import base64
import io
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
KEY = "scalp-ai-model-records-v2"
GRADES = ("정상", "경증", "중증")
FLAKES_GRADES = ("정상", "경중등도", "중증")
SEBUM_GRADES = ("무", "유")


def browser_executable():
    override = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if override:
        return override
    for base, relative in [
        ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
        ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
    ]:
        candidate = Path(os.environ.get(base, "")) / relative
        if candidate.is_file():
            return str(candidate)
    return None


def test_photo(index):
    image = Image.new("RGB", (320, 280))
    image.putdata([
        ((x * (index + 1) + index * 70) % 256, (y * 2 + index * 40) % 256,
         (x + y + index * 100) % 256)
        for y in range(image.height) for x in range(image.width)
    ])
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return {"name": f"synthetic-integration-{index}.png", "mimeType": "image/png", "buffer": output.getvalue()}


def assert_result(result, count):
    assert result["source"] == "model" and result["photo_count"] == count
    assert len(result["metrics"]) == 4 and len(result["per_photo"]) == count
    assert result["configuration_id"] and result["aggregation"] == "mean_probabilities"
    for j, metric in enumerate(result["metrics"]):
        assert len(metric["probabilities"]) == (4 if j == 0 else 3)
        assert abs(sum(metric["probabilities"]) - 1) < 1e-5
        for k, value in enumerate(metric["probabilities"]):
            expected = sum(p["metrics"][j]["probabilities"][k] for p in result["per_photo"]) / count
            assert abs(value - expected) < 1e-6
        assert_grade_metric(metric, j)
    for photo in result["per_photo"]:
        for index, metric in enumerate(photo["metrics"]):
            assert_grade_metric(metric, index)


def assert_grade_metric(metric, index):
    raw = metric["probabilities"]
    grade_probs = ([raw[0], raw[1] + raw[2], raw[3]] if index == 0
                   else [raw[0], raw[1] + raw[2]] if index == 1 else raw)
    labels = FLAKES_GRADES if index == 0 else SEBUM_GRADES if index == 1 else GRADES
    predicted = max(range(len(raw)), key=raw.__getitem__)
    grade = max(range(len(grade_probs)), key=grade_probs.__getitem__)
    assert metric["excluded_classes"] == []
    assert metric["class_index"] == predicted
    assert metric["grade_index"] == grade
    assert metric["label"] == labels[grade]
    assert metric["grade_labels"] == list(labels)
    assert all(abs(a - b) < 1e-6 for a, b in zip(metric["grade_probabilities"], grade_probs))
    assert abs(sum(metric["grade_probabilities"]) - 1) < 1e-5
    assert abs(metric["grade_confidence"] - grade_probs[grade]) < 1e-6
    assert metric["grading_method"] == ("probability_merge" if index in (0, 1) else "argmax")
    assert metric["labels_confirmed"] is True
    assert metric["settings_verified"] is (index in (0, 1))
    assert abs(metric["confidence"] - raw[predicted]) < 1e-6
    if index == 0:
        assert metric["preprocessing_version"] == "flakes-384-square-v1"
    if index == 1:
        assert metric["preprocessing_version"] == "sebum-384-attention-v1"
        assert metric["grade_indices"] == [0, 1, 1]


def set_probabilities(metric, probabilities):
    """Create consistent grade metadata for a fixture using the real result schema."""
    metric["probabilities"] = list(probabilities)
    raw_index = max(range(len(probabilities)), key=probabilities.__getitem__)
    if metric["id"] == "flakes":
        merged, labels = [probabilities[0], probabilities[1] + probabilities[2], probabilities[3]], FLAKES_GRADES
    elif metric["id"] == "sebum" and metric.get("preprocessing_version") == "sebum-384-attention-v1":
        merged, labels = [probabilities[0], probabilities[1] + probabilities[2]], SEBUM_GRADES
    else:
        merged, labels = list(probabilities), GRADES
    grade = max(range(len(merged)), key=merged.__getitem__)
    metric.update(class_index=raw_index, confidence=probabilities[raw_index],
                  grade_probabilities=merged, grade_index=grade, label=labels[grade],
                  grade_labels=list(labels), grade_confidence=merged[grade])
    return metric


def legacy_sebum_metric(metric):
    """Historical model output remains its original three grades, not binary presence."""
    metric.update(class_labels=list(GRADES), labels_confirmed=True, grade_indices=[0, 1, 2],
                  grading_method="argmax", excluded_classes=[], settings_verified=False)
    metric.pop("preprocessing_version", None)
    return set_probabilities(metric, [0.4, 0.35, 0.25])


def assert_customer_copy(page):
    """Audit rendered public text, including screen-reader status, not JS source."""
    text = page.locator("body").inner_text()
    development = re.compile(
        r"시연|데모|테스트|대회용|로컬|이 PC|start\.cmd|localhost|127\.0\.0\.1"
        r"|서버\s*로그|학습\s*코드|처리\s*설정|학습\s*처리|246810|SCALP_",
        re.IGNORECASE,
    )
    match = development.search(text)
    assert match is None, (page.url, match.group(0) if match else None, text)


def assert_customer_entry_routes(page, url):
    for route in ("analysis", "history", "care", "guide", "about", "login", "register",
                  "trend/flakes", "trend/sebum", "trend/hair_loss", "trend/erythema"):
        page.goto(url + "/#" + route)
        page.wait_for_function("!state.authLoading && state.health.status === 'ready'")
        expect(page.locator("#main h1")).to_be_visible()
        assert_customer_copy(page)
    page.goto(url)
    ready(page)


def assert_customer_status_copy(context, url):
    # A service outage/loading state must not become local installation help.
    for status in ("loading", "error"):
        probe = context.new_page()
        probe.route("**/api/health", lambda route, request, kind=status: route.fulfill(
            json={"status": kind, "models": [], "message": "Internal integration status"}))
        probe.goto(url + "/#analysis")
        expect(probe.locator(".status-panel." + status)).to_be_visible()
        assert_customer_copy(probe)
        assert "Internal integration status" not in probe.locator("body").inner_text()
        probe.close()
    probe = context.new_page()
    probe.route("**/api/auth/me", lambda route: route.fulfill(
        status=503, json={"error": "잠시 후 다시 시도해 주세요."}))
    probe.goto(url + "/#login")
    probe.wait_for_function("state.authUnavailable && !state.authLoading")
    assert_customer_copy(probe)
    probe.close()


def assert_grade_presentation(page):
    text = page.locator("#main").inner_text()
    assert "%" not in text, text
    assert "참고번호" not in text, text
    assert "모델 점수" not in text, text


def assert_legacy_grade_mapping(page):
    # Raw legacy values remain intact; grade display restores zero and merges 1 + 2.
    for model_id in ("flakes", "sebum", "hair_loss", "erythema"):
        labels = FLAKES_GRADES if model_id == "flakes" else GRADES
        for grade, label in enumerate(labels):
            if model_id == "flakes":
                probabilities = ([0.7, 0.1, 0.1, 0.1], [0.01, 0.307, 0.336, 0.347],
                                 [0.1, 0.1, 0.1, 0.7])[grade]
                raw_index = max(range(4), key=probabilities.__getitem__)
            else:
                probabilities = [0.1, 0.1, 0.1]
                probabilities[grade] = 0.8
                raw_index = grade
            metric = {
                "id": model_id, "label": f"클래스 {raw_index}", "class_index": raw_index,
                "confidence": probabilities[raw_index], "probabilities": probabilities,
                "class_labels": [f"클래스 {i}" for i in range(len(probabilities))],
                "settings_verified": False,
            }
            index = ("flakes", "sebum", "hair_loss", "erythema").index(model_id)
            actual = page.evaluate(
                """({metric, index}) => ({valid: validMetric(metric, index),
                    grade: metricGrade(metric), label: metricLabel(metric)})""",
                {"metric": metric, "index": index},
            )
            assert actual == {"valid": True, "grade": grade, "label": label}, actual
    prior_exclusion = {
        "id": "flakes", "label": "경증", "class_index": 2,
        "confidence": 0.1, "probabilities": [0.8, 0.05, 0.1, 0.05],
        "class_labels": ["제외", *GRADES], "settings_verified": False,
        "labels_confirmed": True, "grade_index": 1, "excluded_classes": [0],
    }
    actual = page.evaluate("metric => ({valid: validMetric(metric, 0), label: metricLabel(metric)})", prior_exclusion)
    assert actual == {"valid": True, "label": "정상"}, actual


def assert_new_grade_metadata(page, metric):
    assert page.evaluate("metric => validMetric(metric, 0)", metric) is True
    inconsistent = json.loads(json.dumps(metric))
    inconsistent["grade_probabilities"] = [0.1, 0.2, 0.7]
    assert page.evaluate("metric => validMetric(metric, 0)", inconsistent) is False
    inconsistent = json.loads(json.dumps(metric))
    inconsistent["grade_index"] = (metric["grade_index"] + 1) % 3
    assert page.evaluate("metric => validMetric(metric, 0)", inconsistent) is False


def assert_sebum_binary_metadata(page, metric):
    fixture = set_probabilities(json.loads(json.dumps(metric)), [0.4, 0.35, 0.25])
    actual = page.evaluate("metric => ({valid: validMetric(metric, 1), grade: metricGrade(metric), label: metricLabel(metric)})", fixture)
    assert actual == {"valid": True, "grade": 1, "label": "유"}, actual
    for change in ({"grade_probabilities": [0.4, 0.35, 0.25]}, {"grade_index": 2},
                   {"grade_labels": list(GRADES)}, {"grade_indices": [0, 1, 2]},
                   {"label": "경증"}, {"grading_method": "argmax"},
                   {"preprocessing_version": "unknown-sebum-model"}):
        inconsistent = json.loads(json.dumps(fixture))
        inconsistent.update(change)
        assert page.evaluate("metric => validMetric(metric, 1)", inconsistent) is False, change
    missing_marker = json.loads(json.dumps(fixture))
    missing_marker.pop("preprocessing_version")
    assert page.evaluate("metric => validMetric(metric, 1)", missing_marker) is False
    legacy = legacy_sebum_metric(json.loads(json.dumps(fixture)))
    actual = page.evaluate("metric => ({valid: validMetric(metric, 1), grade: metricGrade(metric), label: metricLabel(metric)})", legacy)
    assert actual == {"valid": True, "grade": 0, "label": "정상"}, actual


def ready(page):
    # Service readiness is state, not customer-facing wording.
    page.wait_for_function("state.health.status === 'ready'")


def next_step(page):
    page.locator('[data-action="next"]').click()


def expect_photos(page, count):
    expect(page.locator(".upload-slot img")).to_have_count(count)


def return_from_file_dialog(page):
    # Native pickers return window focus before delivering the input change.
    # Exercise that order; set_input_files alone misses a detached file input.
    with page.expect_response(lambda response: response.url.endswith("/api/auth/me")) as pending:
        page.evaluate('window.dispatchEvent(new Event("focus"))')
    assert pending.value.ok
    pending.value.json()
    page.wait_for_function("!checkingFocusedAccount")


def assert_picker_survives_account_focus(page):
    with page.expect_file_chooser() as pending:
        page.locator('[data-action="select-photos"]').click()
    bulk = pending.value
    return_from_file_dialog(page)
    assert bulk.element.evaluate("input => input.isConnected"), "Account refresh detached the open bulk picker"
    bulk.set_files(test_photo(0))
    expect_photos(page, 1)

    with page.expect_file_chooser() as pending:
        page.locator('label[for="photo-1"]').click()
    single = pending.value
    return_from_file_dialog(page)
    assert single.element.evaluate("input => input.isConnected"), "Account refresh detached the open slot picker"
    single.set_files(test_photo(1))
    expect_photos(page, 2)

    existing = page.locator(".upload-slot img").evaluate_all("images => images.map(image => image.src)")
    with page.expect_file_chooser() as pending:
        page.locator('[data-action="select-photos"]').click()
    cancelled = pending.value
    return_from_file_dialog(page)
    assert cancelled.element.evaluate("input => input.isConnected")
    cancelled.set_files([])
    expect_photos(page, 2)
    assert page.locator(".upload-slot img").evaluate_all("images => images.map(image => image.src)") == existing

    # A failed background identity request must also leave the picker usable.
    original = page.locator("#photos-bulk").element_handle()
    def unavailable_account(route):
        route.abort()
    page.route("**/api/auth/me", unavailable_account)
    try:
        with page.expect_event("requestfailed", predicate=lambda request: request.url.endswith("/api/auth/me")):
            page.evaluate('window.dispatchEvent(new Event("focus"))')
        page.wait_for_function("!checkingFocusedAccount")
        assert original.evaluate("input => input.isConnected")
        assert page.locator(".upload-slot img").evaluate_all("images => images.map(image => image.src)") == existing
    finally:
        page.unroute("**/api/auth/me", unavailable_account)

    # An unchanged identity also keeps input values and nodes while a form is open.
    page.locator('[data-remove="1"]').click()
    page.locator('[data-remove="0"]').click()
    expect_photos(page, 0)
    page.goto(page.url.split("#")[0] + "#register")
    page.locator("#auth-nickname").fill("picker-focus-draft")
    page.locator("#auth-password").fill("246810")
    password = page.locator("#auth-password").element_handle()
    return_from_file_dialog(page)
    assert password.evaluate("input => input.isConnected"), "Quiet account refresh replaced an unchanged form"
    expect(page.locator("#auth-nickname")).to_have_value("picker-focus-draft")
    expect(page.locator("#auth-password")).to_have_value("246810")
    page.locator('[data-nav="analysis"]').click()
    expect(page.locator("#photos-bulk")).to_have_count(1)


def screenshot(page, output, name):
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'}); document.activeElement.blur()")
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    page.screenshot(path=str(output / name), full_page=True)


def assert_layout(page, output, width, route):
    if page.evaluate("document.documentElement.scrollWidth <= innerWidth"):
        return
    screenshot(page, output, f"overflow-{width}-{route}.png")
    outside = page.evaluate("""() => [...document.querySelectorAll('main *')]
        .map(el => ({tag: el.tagName, cls: el.className, right: el.getBoundingClientRect().right,
                     width: el.getBoundingClientRect().width}))
        .filter(el => el.width > 1 && el.right > innerWidth + 1).slice(0, 20)""")
    raise AssertionError((width, route, outside))


def drop_photo(page, photo):
    page.locator(".drop-zone").evaluate(
        """(zone, photo) => {
            const bytes = Uint8Array.from(atob(photo.data), char => char.charCodeAt(0));
            const transfer = new DataTransfer();
            transfer.items.add(new File([bytes], photo.name, {type: photo.mimeType}));
            zone.dispatchEvent(new DragEvent('drop', {
                bubbles: true, cancelable: true, dataTransfer: transfer
            }));
        }""",
        {"name": photo["name"], "mimeType": photo["mimeType"],
         "data": base64.b64encode(photo["buffer"]).decode("ascii")},
    )


def open_details_for(page, selector):
    details = page.locator("details.details-panel").filter(has=page.locator(selector)).first
    if details.count() and details.get_attribute("open") is None:
        details.locator("summary").first.click()



def open_trend(page, metric_id, *, legacy_sebum=False):
    """Menu selection opens a dedicated, single-indicator page and exact scale."""
    page.locator(f'[data-trend-link="{metric_id}"]').first.click()
    page.wait_for_url(f"**#trend/{metric_id}")
    expect(page.locator('[data-nav="history"]')).to_have_attribute('aria-current', 'page')
    expect(page.locator(f'[data-trend-link="{metric_id}"][aria-current="page"]')).to_have_count(1)
    expect(page.locator('[data-trend-panel]')).to_be_visible()
    chart = page.locator('[data-trend-chart]')
    expect(chart).to_have_count(1)
    expect(chart).to_have_attribute('data-metric-id', metric_id)
    expect(chart.locator('circle')).to_have_count(1)
    labels = FLAKES_GRADES if metric_id == 'flakes' else GRADES if metric_id != 'sebum' or legacy_sebum else SEBUM_GRADES
    for label in labels:
        expect(chart).to_contain_text(label)
    expect(page.locator('[data-sebum-chart]')).to_have_count(int(metric_id == 'sebum' and not legacy_sebum))
    expect(page.locator('[data-severity-chart]')).to_have_count(int(metric_id != 'sebum' or legacy_sebum))
    assert_grade_presentation(page)
    assert_customer_copy(page)


def back_to_history(page):
    page.locator('[data-trend-back]').click()
    page.wait_for_url('**#history')
    expect(page.locator('[data-history-trends] [data-trend-link]')).to_have_count(4)
    expect(page.locator('[data-trend-chart]')).to_have_count(0)


def assert_pdf_download(page):
    """A real analysis exports a PDF file without opening the print dialog."""
    page.evaluate("() => { window.__smokePrintCalls = 0; window.print = () => { window.__smokePrintCalls += 1; }; }")
    assert page.evaluate("window.__smokePrintCalls") == 0
    export = page.locator('[data-action="download-pdf"]')
    expect(export).to_have_text(re.compile("PDF"))
    with page.expect_response(
        lambda response: response.url.endswith("/api/report/pdf") and response.request.method == "POST",
        timeout=60000,
    ) as pending_response:
        with page.expect_download(timeout=60000) as pending_download:
            export.click()
    response = pending_response.value
    assert response.ok, response.text()
    download = pending_download.value
    assert download.failure() is None
    assert download.suggested_filename.lower().endswith(".pdf"), download.suggested_filename
    payload = Path(download.path()).read_bytes()
    assert payload.startswith(b"%PDF-"), payload[:100]
    assert len(payload) > 1000, len(payload)
    assert page.evaluate("window.__smokePrintCalls") == 0
    assert page.evaluate("location.hash") == "#report"


def assert_care_plan_and_history(page):
    """Guidance stays in care, while dated interactive practice lives in history."""
    page.locator('[data-nav="care"]').click()
    expect(page.locator(".care-product").first).to_be_visible()
    assert page.locator(".care-product").count() >= 2
    expect(page.locator("#care-personalization")).to_be_visible()
    expect(page.locator("#care-personalization")).to_contain_text("포괄")
    expect(page.locator("[data-care-check]")).to_have_count(0)
    for card in page.locator(".care-product").all():
        assert len(card.inner_text().strip()) > 40
    assert_customer_copy(page)
    page.locator('[data-nav="history"]').click()
    task = page.locator('[data-care-check="gentle-wash"]')
    expect(task).to_be_visible()
    task.check()
    expect(page.locator('[data-care-check="gentle-wash"]')).to_be_checked()
    page.locator('[data-nav="care"]').click()
    expect(page.locator("[data-care-check]")).to_have_count(0)
    page.locator('[data-nav="history"]').click()
    expect(page.locator('[data-care-check="gentle-wash"]')).to_be_checked()
    page.locator('[data-care-check="gentle-wash"]').uncheck()
    expect(page.locator('[data-care-check="gentle-wash"]')).not_to_be_checked()
    assert_customer_copy(page)
    page.evaluate("location.hash = 'report'")
    expect(page.locator(".metric")).to_have_count(4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    url = args.url.rstrip("/")
    deadline = time.monotonic() + 90
    while True:
        health = json.loads(urllib.request.urlopen(url + "/api/health", timeout=10).read())
        if health["status"] == "ready":
            break
        assert health["status"] != "error", health
        assert time.monotonic() < deadline, "Models did not become ready"
        time.sleep(1)
    assert len(health["models"]) == 4 and all(m["ready"] for m in health["models"])

    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=browser_executable())
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors, analysis_requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: analysis_requests.append(req.url)
                if req.url.endswith("/api/analyze") and req.method == "POST" else None)
        page.goto(url)
        ready(page)
        assert_customer_entry_routes(page, url)
        assert_customer_status_copy(context, url)
        expect(page.locator(".sidebar")).to_have_count(0)
        expect(page.locator(".journey")).to_be_visible()
        expect(page.locator('[data-action="analyze"]')).to_have_count(0)
        assert_legacy_grade_mapping(page)
        assert_grade_presentation(page)
        assert_customer_copy(page)
        screenshot(page, output, "analysis-desktop.png")

        # Skipping navigation must keep the current page and move focus to its content.
        page.locator('[data-nav="guide"]').click()
        expect(page.locator("h1")).to_have_text("이렇게 찍으면 준비 끝이에요.")
        expect(page.locator("h1")).to_be_focused()
        page.locator(".skip-link").focus()
        page.keyboard.press("Enter")
        expect(page.locator("#main")).to_be_focused()
        assert page.evaluate("location.hash") == "#guide"
        page.locator('[data-nav="analysis"]').click()
        expect(page.locator('[data-action="next"]')).to_be_visible()

        # The first screen explains preparation; selecting files is a deliberate next step.
        next_step(page)
        expect(page.locator("#photos-bulk")).to_have_count(1)
        expect(page.locator('[data-action="next"]')).to_be_disabled()
        assert not analysis_requests
        assert_picker_survives_account_focus(page)
        assert not analysis_requests
        page.locator("#photo-0").set_input_files(
            {"name": "invalid.svg", "mimeType": "image/svg+xml", "buffer": b"<svg/>"}
        )
        expect(page.locator("#upload-error")).not_to_have_text("")

        # Bulk picking, removal, and drag-and-drop all feed the same photo collection.
        page.locator("#photos-bulk").set_input_files([test_photo(0), test_photo(1)])
        expect_photos(page, 2)
        drop_photo(page, test_photo(2))
        expect_photos(page, 3)
        page.locator('[data-remove="1"]').click()
        expect_photos(page, 2)
        page.locator("#photo-1").set_input_files(test_photo(1))
        expect_photos(page, 3)
        screenshot(page, output, "upload-desktop.png")
        next_step(page)
        expect(page.locator('[data-action="analyze"]')).to_be_enabled()
        page.locator('[data-action="back"]').click()
        expect_photos(page, 3)
        next_step(page)
        assert not analysis_requests, "Navigating/reviewing photos must not send them for analysis"
        screenshot(page, output, "review-desktop.png")

        with page.expect_response(
            lambda response: response.url.endswith("/api/analyze") and response.request.method == "POST",
            timeout=180000,
        ) as pending:
            page.locator('[data-action="analyze"]').click()
            expect(page.locator(".loading-panel")).to_be_visible()
            assert_customer_copy(page)
            assert page.locator('[data-file]:enabled, [data-bulk]:enabled').count() == 0
        response = pending.value
        assert response.ok, response.text()
        result = response.json()
        assert_result(result, 3)
        assert_new_grade_metadata(page, result["metrics"][0])
        assert_sebum_binary_metadata(page, result["metrics"][1])
        page.wait_for_url("**#report")
        expect(page.locator(".metric")).to_have_count(4)
        expect(page.locator('[data-legacy-analysis]')).to_have_count(0)
        for index, metric in enumerate(result["metrics"]):
            expect(page.locator(".metric-value").nth(index)).to_have_text(metric["label"])
        open_details_for(page, ".photo-results")
        expect(page.locator(".photo-results tbody tr")).to_have_count(3)
        expect(page.locator(".probability-list")).to_have_count(0)
        assert_grade_presentation(page)
        assert_customer_copy(page)

        assert_pdf_download(page)
        page.locator('[data-action="save"]').click()
        saved = page.evaluate("key => JSON.parse(localStorage.getItem(key))", KEY)
        assert len(saved) == 1
        assert saved[0]["metrics"][0]["probabilities"] == result["metrics"][0]["probabilities"]
        assert saved[0]["configuration_id"] == result["configuration_id"]
        encoded = json.dumps(saved)
        assert "blob:" not in encoded and "data:image" not in encoded and "synthetic-integration" not in encoded
        screenshot(page, output, "report-desktop.png")
        assert_care_plan_and_history(page)

        # Reopening a prior 256px/zero-excluded record regrades only, not a new inference.
        legacy = json.loads(json.dumps(saved[0]))
        legacy["id"] = "legacy-before-flakes-training-fix"
        legacy["configuration_id"] = "legacy-256-configuration"
        for metric in [legacy["metrics"][0], *[p["metrics"][0] for p in legacy["per_photo"]]]:
            raw = metric["probabilities"]
            previous_index = max((1, 2, 3), key=raw.__getitem__)
            metric["class_index"] = previous_index
            metric["confidence"] = raw[previous_index]
            metric["label"] = GRADES[previous_index - 1]
            metric["class_labels"] = ["제외", *GRADES]
            metric["excluded_classes"] = [0]
            metric["grade_index"] = previous_index - 1
            metric["settings_verified"] = False
            for field in ("grade_probabilities", "grade_labels", "grade_confidence", "grading_method",
                          "grade_indices", "preprocessing_version"):
                metric.pop(field, None)
        for metric in [legacy["metrics"][1], *[photo["metrics"][1] for photo in legacy["per_photo"]]]:
            legacy_sebum_metric(metric)
        page.evaluate("({key, records}) => localStorage.setItem(key, JSON.stringify(records))",
                      {"key": KEY, "records": [*saved, legacy]})
        page.locator('[data-nav="history"]').click()
        expect(page.locator('[data-record]')).to_have_count(2)
        page.locator('[data-record="legacy-before-flakes-training-fix"]').click()
        expect(page.locator('[data-legacy-analysis]')).to_be_visible()
        expect(page.locator('[data-legacy-analysis]')).to_contain_text("다시 분석")
        expected_legacy_grade = max(range(3), key=result["metrics"][0]["grade_probabilities"].__getitem__)
        expect(page.locator('.metric-value').first).to_have_text(FLAKES_GRADES[expected_legacy_grade])
        expect(page.locator('.metric-value').nth(1)).to_have_text("정상")
        expect(page.locator('[data-legacy-sebum]')).to_be_visible()
        expect(page.locator('[data-legacy-sebum]')).to_contain_text("다시 분석")
        assert_customer_copy(page)
        persisted = page.evaluate("key => JSON.parse(localStorage.getItem(key))", KEY)
        assert persisted[1] == legacy, "Viewing legacy data must not overwrite its raw values"
        page.locator('[data-nav="history"]').click()
        expect(page.locator('[data-history-trends] [data-trend-link]')).to_have_count(4)
        expect(page.locator('[data-trend-chart]')).to_have_count(0)
        open_trend(page, 'flakes')
        back_to_history(page)
        open_trend(page, 'sebum', legacy_sebum=True)
        back_to_history(page)
        assert page.evaluate("key => JSON.parse(localStorage.getItem(key))[1]", KEY) == legacy
        page.locator('[data-record="legacy-before-flakes-training-fix"]').click()
        page.evaluate("({key, records}) => localStorage.setItem(key, JSON.stringify(records))",
                      {"key": KEY, "records": saved})

        page.reload()
        expect(page.locator(".empty-state")).to_have_count(1)
        page.locator('[data-nav="history"]').click()
        expect(page.locator("[data-record]")).to_have_count(1)
        expect(page.locator('[data-history-trends] [data-trend-link]')).to_have_count(4)
        expect(page.locator('[data-trend-chart]')).to_have_count(0)
        for metric_id in ('flakes', 'sebum', 'hair_loss', 'erythema'):
            open_trend(page, metric_id)
            if metric_id == 'flakes':
                screenshot(page, output, 'trend-flakes-desktop.png')
            page.reload()
            expect(page.locator('[data-trend-chart]')).to_have_attribute('data-metric-id', metric_id)
            expect(page.locator('[data-trend-chart] circle')).to_have_count(1)
            expect(page.locator('[data-trend-month]')).to_be_visible()
            back_to_history(page)
        open_trend(page, 'flakes')
        month = saved[0]['date'][:7]
        year, number = map(int, month.split('-'))
        previous_month = f"{year if number > 1 else year - 1}-{number - 1 if number > 1 else 12:02d}"
        page.locator('[data-trend-month]').fill(previous_month)
        page.locator('[data-trend-month]').dispatch_event('change')
        expect(page.locator('[data-trend-chart]')).to_have_count(0)
        expect(page.locator('.chart-empty')).to_be_visible()
        page.locator('[data-trend-month]').fill(month)
        page.locator('[data-trend-month]').dispatch_event('change')
        expect(page.locator('[data-trend-chart] circle')).to_have_count(1)
        back_to_history(page)
        day = page.locator(f'[data-date="{saved[0]["date"]}"]')
        selected_date = day.get_attribute('data-date')
        day.focus()
        page.keyboard.press('Enter')
        expect(page.locator(f'[data-date="{selected_date}"]')).to_be_focused()
        open_trend(page, 'flakes')
        page.locator('[data-range="week"]').focus()
        page.keyboard.press('Enter')
        expect(page.locator('[data-range="week"]')).to_be_focused()
        expect(page.locator('[data-range="week"]')).to_have_attribute('aria-pressed', 'true')
        back_to_history(page)
        page.locator("[data-record]").click()
        expect(page.locator(".metric")).to_have_count(4)
        expect(page.locator(".result-thumbnail")).to_have_count(0)
        expect(page.locator('[data-action="save"]')).to_have_count(0)
        expect(page.get_by_role("heading", name="내 기록에 잘 보관했어요")).to_be_visible()

        # Check the real report and the other routes at small, phone, and tablet widths.
        for width in (320, 390, 768):
            page.set_viewport_size({"width": width, "height": 900})
            for route in ("analysis", "history", "guide", "care", "about", "trend/flakes", "trend/sebum", "trend/hair_loss", "trend/erythema"):
                page.goto(url + f"/?layout={width}-{route}#" + route)
                page.wait_for_function("document.querySelector('#main').children.length > 0")
                assert_layout(page, output, width, route.replace("/", "-"))
                assert_customer_copy(page)
                if route.startswith("trend/"):
                    expect(page.locator("[data-trend-chart]")).to_have_attribute("data-metric-id", route.split("/")[1])
                    expect(page.locator("[data-trend-chart] circle")).to_have_count(1)
                    if width == 390 and route == 'trend/sebum':
                        screenshot(page, output, 'trend-sebum-mobile.png')
            page.locator('[data-nav="history"]').click()
            page.locator("[data-record]").click()
            expect(page.locator(".metric")).to_have_count(4)
            assert_layout(page, output, width, "report")
            assert_grade_presentation(page)
            if width == 390:
                screenshot(page, output, "report-mobile.png")

        # A new analysis starts with a clean selection, without repeating the introduction.
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('[data-action="new"]').click()
        ready(page)
        expect_photos(page, 0)
        page.locator("#photo-0").set_input_files(test_photo(2))
        expect_photos(page, 1)
        screenshot(page, output, "upload-mobile.png")
        next_step(page)
        assert len(analysis_requests) == 1
        with page.expect_response(lambda response: response.url.endswith("/api/analyze"), timeout=180000) as pending:
            page.locator('[data-action="analyze"]').click()
        assert pending.value.ok, pending.value.text()
        one = pending.value.json()
        assert_result(one, 1)
        page.wait_for_url("**#report")
        expect(page.locator(".metric")).to_have_count(4)

        # API failures preserve the selected photo for retry and never fabricate a report.
        page.locator('[data-action="new"]').click()
        page.locator("#photos-bulk").set_input_files(test_photo(0))
        expect_photos(page, 1)
        next_step(page)
        page.route("**/api/analyze", lambda route: route.fulfill(status=503, json={"error": "Smoke unavailable"}))
        page.locator('[data-action="analyze"]').click()
        expect(page.locator("#upload-error")).not_to_have_text("")
        assert_customer_copy(page)
        expect(page.locator('[data-action="analyze"]')).to_be_enabled()
        page.locator('[data-action="back"]').click()
        expect_photos(page, 1)
        page.evaluate("location.hash = 'report'")
        expect(page.locator(".empty-state")).to_have_count(1)

        # A local HTML entry gives service-address guidance without developer setup commands.
        local = context.new_page()
        local.goto((ROOT / "dist" / "index.html").as_uri())
        expect(local.locator(".server-notice")).to_be_visible()
        assert_customer_copy(local)
        assert local.locator('a[href*="127.0.0.1"], a[href*="localhost"]').count() == 0
        expect(local.locator('[data-action="analyze"]')).to_have_count(0)
        assert not errors, errors
        browser.close()
    print(json.dumps({
        "result": "PASS", "models": 4, "three_photo_ms": result["elapsed_ms"],
        "one_photo_ms": one["elapsed_ms"], "configuration_id": result["configuration_id"],
        "checks": "customer-facing wording across public routes, loading/errors and file entry; training-aligned flakes and binary sebum merging, separate sebum chart, preserved legacy three-grade sebum, restored class zero, legacy records, no displayed percentages, guided steps, keyboard navigation, native picker focus/selection/cancel and failed identity refresh, bulk/drop/remove, preserved photos, no premature upload, real inference, "
                  "mean aggregation, direct PDF download without print dialog, concrete care products, optional-gender generic guidance, dated practice checklist in history, dedicated per-indicator trend routes/menu/scales/month/week/keyboard/reload, storage/reload, history, 320/390/768 layouts, API failure/retry, file entry",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

