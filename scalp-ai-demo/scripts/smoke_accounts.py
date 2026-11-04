"""Check local-demo accounts and personalized care with an isolated real server.

Starts a second local server with a temporary SQLite database. Uses synthetic
images to exercise integration; does not measure scalp-model accuracy or touch
the normal demonstration database.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4
from contextlib import closing
from datetime import date, timedelta

from playwright.sync_api import expect, sync_playwright

from smoke_web import (
    KEY, assert_grade_presentation, assert_layout, assert_result,
    browser_executable, next_step, ready, screenshot, test_photo, legacy_sebum_metric, set_probabilities, assert_customer_copy, open_trend, back_to_history,
)

ROOT = Path(__file__).resolve().parents[1]
TITLE = "딥러닝 기반 AI 두피 관리 서비스"


def wait_for_server(process, url, logfile):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Isolated server exited: " + logfile.read_text(encoding="utf-8", errors="replace")[-5000:])
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=5) as response:
                health = json.loads(response.read())
            assert health["status"] != "error", health
            if health["status"] == "ready":
                assert len(health["models"]) == 4 and all(model["ready"] for model in health["models"])
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.5)
    raise AssertionError("Isolated server did not load all four models in 180 seconds")


def auth_form(page, url, mode, nickname, password, success=True, gender=None):
    page.goto(url + "/#" + mode)
    expect(page.locator("[data-auth-form]")).to_have_attribute("data-auth-form", mode)
    assert_customer_copy(page)
    page.locator("#auth-nickname").fill(nickname)
    page.locator("#auth-password").fill(password)
    if mode == "register" and gender is not None:
        page.locator("#auth-gender-consent").check()
        page.locator("#auth-gender").select_option(gender)
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/" + mode)
        and response.request.method == "POST",
        timeout=30000,
    ) as pending:
        page.locator("#auth-password").press("Enter")
    response = pending.value
    if success:
        assert response.ok, response.text()
        expect(page.locator("[data-account-name]")).to_contain_text(nickname)
        expect(page.locator("[data-auth-form]")).to_have_count(0)
        return response.json()["user"]
    assert not response.ok
    expect(page.locator("#auth-error")).to_be_visible()
    expect(page.locator("#auth-error")).not_to_have_text("")
    assert_customer_copy(page)
    return None


def logout(page):
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/logout") and response.request.method == "POST"
    ) as pending:
        page.locator('[data-action="logout"]').click()
    assert pending.value.ok, pending.value.text()
    expect(page.locator("[data-account-name]")).to_have_count(0)


def api_records(context):
    response = context.request.get("/api/records")
    assert response.ok, response.text()
    return response.json()["records"]


def legacy_record(result):
    legacy = copy.deepcopy(result)
    legacy.pop("save_token", None)
    legacy["id"] = "guest-legacy-" + uuid4().hex
    legacy["configuration_id"] = "legacy-256-configuration"
    legacy["settings_verified"] = False
    for metric in [legacy["metrics"][0], *[photo["metrics"][0] for photo in legacy["per_photo"]]]:
        metric["probabilities"] = [0.8, 0.05, 0.1, 0.05]
        metric.update(class_index=2, confidence=0.1, label="경증",
                      class_labels=["제외", "정상", "경증", "중증"],
                      excluded_classes=[0], grade_index=1, settings_verified=False)
        for field in ("grade_probabilities", "grade_labels", "grade_confidence",
                      "grading_method", "grade_indices", "preprocessing_version"):
            metric.pop(field, None)
    for metric in [legacy["metrics"][1], *[photo["metrics"][1] for photo in legacy["per_photo"]]]:
        legacy_sebum_metric(metric)
    return legacy


def check_plan_rules(page, result):
    # These fixtures test only recommendation selection; authentication/records
    # below always use real server responses and a real model result.
    normal = copy.deepcopy(result)
    for index, metric in enumerate(normal["metrics"]):
        set_probabilities(metric, [0.85, 0.05, 0.05, 0.05] if index == 0 else [0.8, 0.1, 0.1])
    merged = copy.deepcopy(normal)
    set_probabilities(merged["metrics"][0], [0.01, 0.307, 0.336, 0.347])
    severe = copy.deepcopy(normal)
    set_probabilities(severe["metrics"][3], [0.05, 0.05, 0.9])
    sebum = copy.deepcopy(normal)
    set_probabilities(sebum["metrics"][1], [0.4, 0.35, 0.25])
    old_sebum = copy.deepcopy(normal)
    legacy_sebum_metric(old_sebum["metrics"][1])
    plans = page.evaluate(
        """({normal, merged, severe, sebum, old_sebum}) => ({
            empty: buildCarePlan(null), normal: buildCarePlan(normal),
            merged: buildCarePlan(merged), severe: buildCarePlan(severe),
            sebum: buildCarePlan(sebum), old_sebum: buildCarePlan(old_sebum)
        })""",
        {"normal": normal, "merged": merged, "severe": severe, "sebum": sebum, "old_sebum": old_sebum},
    )
    assert plans["empty"]["items"] == []
    baseline = {"gentle-wash", "low-heat", "observe"}
    assert {item["id"] for item in plans["normal"]["items"]} == baseline
    assert {item["id"] for item in plans["merged"]["items"]} == baseline | {"flakes-care"}
    assert {item["id"] for item in plans["severe"]["items"]} == baseline | {"redness-care"}
    assert "경중등도" in json.dumps(plans["merged"]["items"], ensure_ascii=False)
    assert {item["id"] for item in plans["sebum"]["items"]} == baseline | {"sebum-care"}
    assert {item["id"] for item in plans["old_sebum"]["items"]} == baseline
    sebum_item = next(item for item in plans["sebum"]["items"] if item["id"] == "sebum-care")
    assert "유" in sebum_item["reason"] and "경증" not in sebum_item["reason"] and "중증" not in sebum_item["reason"]
    for plan in plans.values():
        for item in plan["items"]:
            assert all(item.get(key) for key in ("id", "title", "text", "reason"))
    assert plans["merged"]["sources"] and plans["merged"]["note"]


def run_flow(url, output):
    nickname, password_a, password_b = "회원검증" + uuid4().hex[:10], "010101", "020202"
    nickname_b = nickname + "다른회원"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=browser_executable())
        context = browser.new_context(base_url=url, viewport={"width": 1280, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        ready(page)
        expect(page.locator(".brand")).to_contain_text(TITLE)
        assert TITLE in page.title()
        expect(page.locator(".site-footer")).to_contain_text(TITLE)

        first = auth_form(page, url, "register", nickname, password_a, gender="female")
        assert first.get("id") is not None and first["gender"] == "female" and first["gender_consent"] is True
        duplicate = context.request.post("/api/auth/register", data={"nickname": nickname, "password": password_b})
        assert duplicate.status == 409 and duplicate.json()["code"] == "nickname_taken"
        availability = context.request.get("/api/auth/nickname", params={"nickname": nickname})
        assert availability.ok and availability.json()["available"] is False
        invalid_consent = context.request.post("/api/auth/register", data={"nickname": nickname_b, "password": password_b, "gender": "male"})
        assert invalid_consent.status == 400
        assert api_records(context) == []
        print("Registered account A; starting real image analysis.", flush=True)
        page.goto(url + "/#analysis")
        ready(page)
        next_step(page)
        page.locator("#photos-bulk").set_input_files(test_photo(0))
        expect(page.locator(".upload-slot img")).to_have_count(1)
        next_step(page)
        with page.expect_response(
            lambda response: response.url.endswith("/api/analyze") and response.request.method == "POST",
            timeout=180000,
        ) as pending:
            page.locator('[data-action="analyze"]').click()
        assert pending.value.ok, pending.value.text()
        result = pending.value.json()
        assert_result(result, 1)
        assert result.get("save_token"), "Signed-in analysis must include proof for account saving"
        page.wait_for_url("**#report")
        expect(page.locator(".metric")).to_have_count(4)
        with page.expect_response(
            lambda response: response.url.endswith("/api/records") and response.request.method == "POST"
        ) as pending:
            page.locator('[data-action="save"]').click()
        assert pending.value.ok, pending.value.text()
        expect(page.locator('[data-action="save"]')).to_have_count(0)
        records = api_records(context)
        assert len(records) == 1 and records[0]["id"] == result["id"]
        encoded = json.dumps(records)
        assert all(fragment not in encoded for fragment in ("blob:", "data:image", "synthetic-integration", "save_token"))
        assert records[0]["metrics"][0]["probabilities"] == result["metrics"][0]["probabilities"]
        assert result["metrics"][1]["label"] in ("무", "유")
        check_plan_rules(page, result)

        # A pre-existing guest record must survive account operations byte-for-byte.
        guest = legacy_record(result)
        guest_json = json.dumps([guest], ensure_ascii=False)
        page.evaluate("({key, value}) => localStorage.setItem(key, value)", {"key": KEY, "value": guest_json})
        page.reload()
        page.locator('[data-nav="history"]').click()
        expect(page.locator("[data-record]")).to_have_count(1)
        expect(page.locator("[data-record]")).to_have_attribute("data-record", result["id"])
        expect(page.locator('[data-history-trends] [data-trend-link]')).to_have_count(4)
        expect(page.locator('[data-trend-chart]')).to_have_count(0)
        open_trend(page, 'flakes')
        back_to_history(page)
        open_trend(page, 'sebum')
        back_to_history(page)
        page.locator("[data-record]").click()
        expect(page.locator(".result-thumbnail")).to_have_count(0)
        expect(page.locator(".metric-value").nth(1)).to_have_text(result["metrics"][1]["label"])
        assert_grade_presentation(page)
        assert_customer_copy(page)
        screenshot(page, output, "account-report-desktop.png")

        page.locator('[data-nav="care"]').click()
        expect(page.locator("[data-care-check]")).to_have_count(0)
        assert_customer_copy(page)
        screenshot(page, output, "account-care-desktop.png")
        page.locator('[data-nav="history"]').click()
        expect(page.locator("[data-care-check]")).not_to_have_count(0)
        checkbox = page.locator('[data-care-check="gentle-wash"]')
        expect(checkbox).not_to_be_checked()
        with page.expect_response(lambda response: "/api/care-checks" in response.url and response.request.method == "PUT") as pending:
            checkbox.check()
        assert pending.value.ok, pending.value.text()
        today = page.evaluate("today()")
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        if yesterday[:7] != today[:7]:
            page.locator('[data-action="prev-month"]').click()
        page.locator(f'[data-date="{yesterday}"]').click()
        previous = page.locator('[data-care-check="low-heat"]')
        expect(previous).to_be_enabled()
        expect(previous).not_to_be_checked()
        with page.expect_response(lambda response: "/api/care-checks" in response.url and response.request.method == "PUT") as pending:
            previous.check()
        assert pending.value.ok and pending.value.json()["date"] == yesterday, pending.value.text()
        month = context.request.get("/api/care-checks", params={"month": yesterday[:7]})
        assert month.ok, month.text()
        assert next(day for day in month.json()["days"] if day["date"] == yesterday)["checks"] == ["low-heat"]
        page.reload()
        if yesterday[:7] != today[:7]:
            page.locator('[data-action="prev-month"]').click()
        page.locator(f'[data-date="{yesterday}"]').click()
        expect(page.locator('[data-care-check="low-heat"]')).to_be_checked()
        expect(page.locator('[data-care-check="gentle-wash"]')).not_to_be_checked()
        if yesterday[:7] != today[:7]:
            page.locator('[data-action="next-month"]').click()
        page.locator(f'[data-date="{today}"]').click()
        expect(page.locator('[data-care-check="gentle-wash"]')).to_be_checked()
        expect(page.locator('[data-care-check="low-heat"]')).not_to_be_checked()
        future = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
        if page.locator(f'[data-date="{future}"]').count():
            expect(page.locator(f'[data-date="{future}"]')).to_be_disabled()
        assert_customer_copy(page)
        screenshot(page, output, "account-care-calendar.png")
        print("Account A record and dated calendar care states persisted independently after reload.", flush=True)

        logout(page)
        assert context.request.get("/api/records").status == 401
        assert page.evaluate("key => localStorage.getItem(key)", KEY) == guest_json
        page.locator('[data-nav="history"]').click()
        expect(page.locator("[data-record]")).to_have_count(1)
        expect(page.locator("[data-record]")).to_have_attribute("data-record", guest["id"])
        page.locator("[data-record]").click()
        expect(page.locator(".metric-value").nth(1)).to_have_text("정상")
        expect(page.locator("[data-legacy-sebum]")).to_be_visible()
        assert page.evaluate("key => localStorage.getItem(key)", KEY) == guest_json

        # New accounts use unique IDs; omitting optional gender stays supported.
        second = auth_form(page, url, "register", nickname_b, password_b)
        assert second["gender"] is None and second["gender_consent"] is False
        assert second["id"] != first["id"]
        assert api_records(context) == []
        page.locator('[data-nav="history"]').click()
        expect(page.locator("[data-record]")).to_have_count(0)
        expect(page.locator("[data-care-check]:checked")).to_have_count(0)
        checks = context.request.get("/api/care-checks?date=" + result["date"])
        assert checks.ok, checks.text()
        assert checks.json()["checks"] == []
        # An analysis proof from A must not allow B to attach A's record.
        rejected = context.request.post("/api/records", data={"record": result, "save_token": result["save_token"]})
        assert rejected.status in (400, 403), rejected.text()
        assert api_records(context) == []
        assert page.evaluate("key => localStorage.getItem(key)", KEY) == guest_json
        logout(page)

        auth_form(page, url, "login", nickname, "999999", success=False)
        first_again = auth_form(page, url, "login", nickname, password_a)
        assert first_again["id"] == first["id"]
        expect(page.locator("[data-account-name]")).to_contain_text(nickname)
        assert len(api_records(context)) == 1
        page.locator('[data-nav="history"]').click()
        expect(page.locator("[data-record]")).to_have_count(1)
        page.locator("[data-record]").click()
        expect(page.locator(".metric")).to_have_count(4)
        page.locator('[data-nav="history"]').click()
        expect(page.locator('[data-care-check="gentle-wash"]')).to_be_checked()
        assert page.evaluate("key => localStorage.getItem(key)", KEY) == guest_json

        # Cookies are shared across tabs. A tab displaying A must not write A's
        # checklist into B when another tab has changed the authenticated account.
        stale = context.new_page()
        stale.goto(url + "/#history")
        expect(stale.locator('[data-care-check="gentle-wash"]')).to_be_checked()
        stale.wait_for_function("id => state.user?.id === id", arg=first["id"])
        logout(page)
        auth_form(page, url, "login", nickname_b, password_b)
        with stale.expect_response(
            lambda response: "/api/care-checks" in response.url and response.request.method == "PUT"
        ) as pending:
            # Dispatch the click without a window-focus event, so this exercises
            # the server guard even if the tab has not refreshed its login state.
            stale.locator('[data-care-check="gentle-wash"]').evaluate("input => input.click()")
        assert pending.value.status == 409, pending.value.text()
        assert pending.value.json()["code"] == "account_changed"
        stale.wait_for_function("id => state.user?.id === id && !state.authLoading", arg=second["id"])
        expect(stale.locator("[data-care-check]:checked")).to_have_count(0)
        assert stale.evaluate("state.result === null && state.accountRecords.length === 0")
        check_b = context.request.get("/api/care-checks?date=" + result["date"])
        assert check_b.ok and check_b.json()["checks"] == []
        stale.close()
        logout(page)
        auth_form(page, url, "login", nickname, password_a)
        page.locator('[data-nav="history"]').click()
        expect(page.locator('[data-care-check="gentle-wash"]')).to_be_checked()
        assert len(api_records(context)) == 1

        # Member changes require the current password, rotate credentials and
        # invalidate other sessions without removing the saved analysis/history.
        other_session = browser.new_context(base_url=url)
        logged_in = other_session.request.post("/api/auth/login", data={"nickname": nickname, "password": password_a})
        assert logged_in.ok, logged_in.text()
        page.goto(url + "/#profile")
        expect(page.locator("[data-profile-form]")).to_be_visible()
        changed_nickname, changed_password = nickname + "수정", "new-sample-only-password"
        page.locator("#profile-nickname").fill(changed_nickname)
        page.locator("#profile-current-password").fill("wrong-current-password")
        page.locator("#profile-new-password").fill(changed_password)
        page.locator("#profile-confirm-password").fill(changed_password)
        page.locator("#profile-gender-consent").check()
        page.locator("#profile-gender").select_option("male")
        with page.expect_response(lambda response: response.url.endswith("/api/auth/profile") and response.request.method == "PATCH") as pending:
            page.locator('[data-profile-form] [type="submit"]').click()
        assert pending.value.status == 403, pending.value.text()
        assert context.request.get("/api/auth/me").json()["user"]["nickname"] == nickname
        page.locator("#profile-current-password").fill(password_a)
        with page.expect_response(lambda response: response.url.endswith("/api/auth/profile") and response.request.method == "PATCH") as pending:
            page.locator('[data-profile-form] [type="submit"]').click()
        assert pending.value.ok, pending.value.text()
        updated = pending.value.json()["user"]
        assert updated["id"] == first["id"] and updated["gender"] == "male" and updated["profile_version"] > first["profile_version"]
        expect(page.locator("[data-account-name]")).to_contain_text(changed_nickname)
        assert other_session.request.get("/api/auth/me").json()["user"] is None
        assert len(api_records(context)) == 1
        old_login = other_session.request.post("/api/auth/login", data={"nickname": nickname, "password": password_a})
        assert old_login.status == 401
        new_login = other_session.request.post("/api/auth/login", data={"nickname": changed_nickname, "password": changed_password})
        assert new_login.ok and new_login.json()["user"]["id"] == first["id"]
        page.goto(url + "/#profile")
        page.locator("#profile-current-password").fill(changed_password)
        page.locator("#profile-gender-consent").uncheck()
        with page.expect_response(lambda response: response.url.endswith("/api/auth/profile") and response.request.method == "PATCH") as pending:
            page.locator('[data-profile-form] [type="submit"]').click()
        assert pending.value.ok, pending.value.text()
        withdrawn = pending.value.json()["user"]
        assert withdrawn["gender"] is None and withdrawn["gender_consent"] is False
        page.reload()
        expect(page.locator("#profile-gender-consent")).not_to_be_checked()
        expect(page.locator("#profile-gender")).to_be_disabled()
        assert len(api_records(context)) == 1
        month = context.request.get("/api/care-checks", params={"month": yesterday[:7]})
        assert month.ok and any(day["date"] == yesterday and day["checks"] == ["low-heat"] for day in month.json()["days"])
        screenshot(page, output, "account-profile.png")
        other_session.close()
        nickname, password_a = changed_nickname, changed_password

        # Shared header and all new routes must fit narrow screens too.
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            for route in ("analysis", "history", "care", "guide", "about", "profile"):
                page.goto(url + "/?account-layout=" + str(width) + "-" + route + "#" + route)
                expect(page.locator("#main h1")).to_be_visible()
                expect(page.locator("[data-account-name]")).to_contain_text(nickname)
                assert_layout(page, output, width, route)
                assert_customer_copy(page)
                if width in (390, 1280) and route == "care":
                    screenshot(page, output, "account-care-" + str(width) + ".png")
        logout(page)
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            for route in ("login", "register"):
                page.goto(url + "/#" + route)
                expect(page.locator("[data-auth-form]")).to_be_visible()
                assert_layout(page, output, width, route)
                assert_customer_copy(page)
                if width in (390, 1280):
                    screenshot(page, output, "account-" + route + "-" + str(width) + ".png")
        assert not errors, errors
        browser.close()
    return {"record_id": result["id"], "one_photo_ms": result["elapsed_ms"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    # Never stop or reuse an unrelated process already listening on this port.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scalp-account-e2e-") as temporary:
        directory = Path(temporary)
        database, logfile = directory / "accounts.sqlite3", directory / "server.log"
        env = os.environ.copy()
        env.update(SCALP_DB_PATH=str(database), PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        with logfile.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-X", "utf8", str(ROOT / "server.py"), "--port", str(args.port)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                url = "http://127.0.0.1:" + str(args.port)
                wait_for_server(process, url, logfile)
                details = run_flow(url, output)
            except Exception:
                print(logfile.read_text(encoding="utf-8", errors="replace")[-5000:], file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
                    else:
                        process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        assert database.is_file(), "The isolated SQLite database was not created"
        with closing(sqlite3.connect(database)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "users" in tables
            assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        summary = {
            "result": "PASS", **details,
            "checks": "real inference; Enter registration/login and login errors; unique nickname normalization; optional gender/explicit consent; "
                      "account-owned record save/reload and cross-account isolation; owner-bound proof; "
                      "dated calendar care persistence and isolation; current-password profile edit/session revocation/consent withdrawal; stale-tab account-change guard; binary sebum and legacy grade-driven plans; preserved guest legacy data; "
                      "no saved images; title; 320/390/768/1280 layouts; isolated temporary SQLite",
        }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

