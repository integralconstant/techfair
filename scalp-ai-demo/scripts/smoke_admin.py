"""Exercise admin operations with a temporary database and actual model server.

Production accounts are never used or altered. Synthetic photos test integration,
not scalp-model accuracy. Generated reset codes are not printed or persisted.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from accounts import AccountStore
from smoke_web import assert_layout, assert_result, browser_executable, next_step, ready, screenshot, test_photo, assert_customer_copy
from smoke_accounts import auth_form, wait_for_server


ADMIN_PASSWORD = "isolated-operator-test-password"
MEMBER_NICKNAME = "같은닉네임검증"


def login_api(context, nickname, password):
    response = context.request.post("/api/auth/login", data={"nickname": nickname, "password": password})
    assert response.ok, response.text()
    return response.json()["user"]


def create_analysis(page):
    page.goto(page.url.split("#")[0] + "#analysis")
    ready(page)
    next_step(page)
    page.locator("#photos-bulk").set_input_files(test_photo(0))
    expect(page.locator(".upload-slot img")).to_have_count(1)
    next_step(page)
    with page.expect_response(lambda response: response.url.endswith("/api/analyze") and response.request.method == "POST", timeout=180000) as pending:
        page.locator('[data-action="analyze"]').click()
    assert pending.value.ok, pending.value.text()
    result = pending.value.json()
    assert_result(result, 1)
    page.wait_for_url("**#report")
    assert_customer_copy(page)
    with page.expect_response(lambda response: response.url.endswith("/api/records") and response.request.method == "POST") as pending:
        page.locator('[data-action="save"]').click()
    assert pending.value.ok, pending.value.text()
    expect(page.locator('[data-action="save"]')).to_have_count(0)
    page.locator('[data-nav="history"]').click()
    expect(page.locator('[data-care-check="observe"]')).to_be_enabled()
    with page.expect_response(lambda response: "/api/care-checks" in response.url and response.request.method == "PUT") as pending:
        page.locator('[data-care-check="observe"]').check()
    assert pending.value.ok, pending.value.text()
    return result


def action_button(page, user_id, action):
    return page.locator(f'[data-admin-user="{user_id}"] [data-admin-action="{action}"][data-user-id="{user_id}"]')


def run_flow(url, output, users):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=browser_executable())
        member_context = browser.new_context(base_url=url, viewport={"width": 1280, "height": 1000})
        other_context = browser.new_context(base_url=url, viewport={"width": 1280, "height": 1000})
        admin_context = browser.new_context(base_url=url, viewport={"width": 1280, "height": 1000})
        member, admin = member_context.new_page(), admin_context.new_page()
        errors = []
        member.on("pageerror", lambda error: errors.append(str(error)))
        admin.on("pageerror", lambda error: errors.append(str(error)))
        target, sibling, operator = users
        auth_form(member, url, "login", MEMBER_NICKNAME, "111111")
        expect(member.locator("[data-admin-link]")).to_have_count(0)
        assert member_context.request.get("/api/admin/users").status == 403
        member.goto(url + "/#admin")
        expect(member.locator("[data-admin-denied]")).to_be_visible()
        expect(member.locator("[data-admin-user]")).to_have_count(0)
        result = create_analysis(member)

        # The duplicate nickname's other account has an independent real result.
        login_api(other_context, MEMBER_NICKNAME, "222222")
        response = other_context.request.post("/api/analyze", multipart={"photos": test_photo(1)}, timeout=180000)
        assert response.ok, response.text()
        other_result = response.json()
        assert_result(other_result, 1)
        saved = other_context.request.post("/api/records", data={"record": other_result, "save_token": other_result["save_token"]})
        assert saved.ok, saved.text()
        checked = other_context.request.put("/api/care-checks", data={"date": other_result["date"], "checks": ["low-heat"]})
        assert checked.ok, checked.text()

        auth_form(admin, url, "login", "운영검증", ADMIN_PASSWORD)
        expect(admin.locator("[data-admin-link]")).to_be_visible()
        admin.locator("[data-admin-link]").click()
        expect(admin.locator("[data-admin-dashboard]")).to_be_visible()
        assert "시연" not in admin.locator("body").inner_text()
        expect(admin.locator("[data-admin-user]")).to_have_count(3)
        expect(admin.locator('[data-admin-count="accounts"]')).to_have_text(re.compile(r"^3(?:개|명)?$"))
        expect(admin.locator('[data-admin-count="records"]')).to_have_text(re.compile(r"^2(?:개|건|회|명)?$"))
        expect(admin.locator("[data-admin-models]")).to_contain_text("피지")
        health = admin_context.request.get("/api/admin/overview").json()["health"]
        assert len(health["models"]) == 4 and all(model["ready"] for model in health["models"])
        assert admin.locator(f'[data-admin-user="{operator["id"]}"] [data-admin-action]').count() == 0

        admin.once("dialog", lambda dialog: dialog.accept())
        with admin.expect_response(lambda response: response.url.endswith(f"/api/admin/users/{target['id']}/reset-password") and response.request.method == "POST") as pending:
            action_button(admin, target["id"], "reset-password").click()
        response = pending.value
        assert response.ok, response.text()
        print("Real analyses and administrator password reset passed.", flush=True)
        reset_password = response.json()["temporary_password"]
        expect(admin.locator("[data-admin-password]")).to_have_text(reset_password)
        assert member_context.request.get("/api/auth/me").json()["user"] is None
        assert other_context.request.get("/api/auth/me").json()["user"]["id"] == sibling["id"]
        assert reset_password not in json.dumps(admin_context.request.get("/api/admin/actions").json())
        assert reset_password not in admin.evaluate("JSON.stringify(localStorage)")
        # A secret returned once is cleared when leaving the administration route.
        admin.goto(url + "/#about")
        expect(admin.locator("[data-admin-password]")).to_have_count(0)
        admin.goto(url + "/#admin")
        expect(admin.locator("[data-admin-user]")).to_have_count(3)
        expect(admin.locator("[data-admin-password]")).to_have_count(0)
        # A revoked session is detected on the old page's next account request.
        with member.expect_response(lambda response: "/api/care-checks" in response.url and response.request.method == "PUT") as pending:
            member.locator('[data-care-check="observe"]').evaluate("input => input.click()")
        assert pending.value.status in (401, 409), pending.value.text()
        member.wait_for_function("state.user === null && !state.authLoading")
        auth_form(member, url, "login", MEMBER_NICKNAME, reset_password)
        assert member_context.request.get("/api/records").json()["records"][0]["id"] == result["id"]
        rejected = member_context.request.post("/api/records", data={"record": result, "save_token": result["save_token"]})
        assert rejected.status == 403, rejected.text()
        member.locator('[data-nav="history"]').click()
        expect(member.locator('[data-care-check="observe"]')).to_be_checked()

        admin.once("dialog", lambda dialog: dialog.dismiss())
        action_button(admin, target["id"], "clear-data").click()
        assert len(member_context.request.get("/api/records").json()["records"]) == 1
        admin.once("dialog", lambda dialog: dialog.accept())
        with admin.expect_response(lambda response: response.url.endswith(f"/api/admin/users/{target['id']}/clear-data") and response.request.method == "POST") as pending:
            action_button(admin, target["id"], "clear-data").click()
        assert pending.value.ok, pending.value.text()
        assert pending.value.json()["deleted_records"] == 1
        assert pending.value.json()["deleted_care_days"] == 1
        print("Administrator clear-data confirmation and deletion passed.", flush=True)
        # Click without a focus event: the old page must send its stale epoch.
        with member.expect_response(lambda response: "/api/care-checks" in response.url and response.request.method == "PUT") as pending:
            member.locator('[data-care-check="observe"]').evaluate("input => input.click()")
        assert pending.value.status == 409, pending.value.text()
        assert pending.value.json()["code"] == "data_changed"
        member.wait_for_function("state.result === null && state.accountRecords.length === 0 && !state.authLoading")
        assert member_context.request.get("/api/records").json()["records"] == []
        assert len(other_context.request.get("/api/records").json()["records"]) == 1

        admin.once("dialog", lambda dialog: dialog.accept())
        with admin.expect_response(lambda response: response.url.endswith(f"/api/admin/users/{sibling['id']}") and response.request.method == "DELETE") as pending:
            action_button(admin, sibling["id"], "delete-user").click()
        assert pending.value.ok, pending.value.text()
        expect(admin.locator("[data-admin-user]")).to_have_count(2)
        expect(admin.locator('[data-admin-count="accounts"]')).to_have_text(re.compile(r"^2(?:개|건|회|명)?$"))
        expect(admin.locator('[data-admin-count="records"]')).to_have_text(re.compile(r"^0(?:개|건|회)?$"))
        assert other_context.request.get("/api/auth/me").json()["user"] is None
        audit = admin_context.request.get("/api/admin/actions").json()["actions"]
        deleted = next(item for item in audit if item["action"] == "user_deleted")
        assert deleted["target_id"] == sibling["id"] and deleted["target_nickname"] == MEMBER_NICKNAME
        expect(admin.locator("[data-admin-actions]")).to_contain_text(MEMBER_NICKNAME)
        for width in (320, 390, 768, 1280):
            admin.set_viewport_size({"width": width, "height": 900})
            assert_layout(admin, output, width, "admin")
            if width in (390, 1280):
                screenshot(admin, output, "admin-" + str(width) + ".png")
        with admin.expect_response(lambda response: response.url.endswith("/api/auth/logout") and response.request.method == "POST"):
            admin.locator('[data-action="logout"]').click()
        expect(admin.locator("[data-admin-link]")).to_have_count(0)
        expect(admin.locator("[data-admin-password]")).to_have_count(0)
        assert admin_context.request.get("/api/admin/overview").status == 401
        assert not errors, errors
        browser.close()
    return {"one_photo_ms": result["elapsed_ms"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scalp-admin-e2e-") as temporary:
        directory = Path(temporary)
        database, logfile = directory / "admin.sqlite3", directory / "server.log"
        store = AccountStore(database)
        operator = store.create_admin("운영검증", ADMIN_PASSWORD)
        target = store.register({"nickname": MEMBER_NICKNAME, "password": "111111"})
        sibling = store.register({"nickname": MEMBER_NICKNAME + "별도", "password": "222222"})
        # Preserve legacy duplicate-ID targeting coverage without bypassing the
        # new public uniqueness policy through a second signup request.
        with store.connection() as database_connection:
            database_connection.execute("UPDATE users SET nickname=?,nickname_key=? WHERE id=?",
                                        (MEMBER_NICKNAME, store.nickname_key(MEMBER_NICKNAME), sibling["id"]))
        sibling["nickname"] = MEMBER_NICKNAME
        env = {**os.environ, "SCALP_DB_PATH": str(database), "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        with logfile.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "server.py"), "--port", str(args.port)],
                                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                url = "http://127.0.0.1:" + str(args.port)
                wait_for_server(process, url, logfile)
                details = run_flow(url, output, (target, sibling, operator))
            except Exception:
                print(logfile.read_text(encoding="utf-8", errors="replace")[-5000:], file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    if os.name == "nt":
                        # Stop this owned process and its venv interpreter child;
                        # otherwise the child can briefly retain the redirected log.
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       capture_output=True, timeout=20)
                    else:
                        process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        print(json.dumps({"result": "PASS", **details,
            "checks": "real inference; admin-only navigation/API; duplicate-nickname ID targeting; password reset and session revocation; "
                      "clear cancellation and epoch invalidation; deletion cascade; audit identity snapshots; transient secret cleared; "
                      "model status/counts; 320/390/768/1280 layouts; isolated temporary database"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
