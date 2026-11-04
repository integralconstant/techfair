"""Camera-to-photo integration using Chrome fake hardware, never a real USB device."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from smoke_web import browser_executable

ROOT = Path(__file__).resolve().parents[1]


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_executable(), headless=True,
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        context = browser.new_context(viewport={"width": 1280, "height": 1000}, permissions=["camera"])
        context.add_init_script("""(() => {
          window.__cameraCalls = 0;
          if (navigator.mediaDevices?.getUserMedia) {
            const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = (...args) => { window.__cameraCalls++; return original(...args); };
          }
        })();""")
        page = context.new_page()
        uploads = []
        page.on("request", lambda request: uploads.append(request.url) if request.url.endswith("/api/analyze") else None)
        page.goto("http://127.0.0.1:8000/#analysis")
        page.wait_for_function("state.health.status === 'ready' && !state.authLoading")
        page.locator('[data-action="next"]').click()
        expect(page.locator('[data-scalp-camera]')).to_be_visible()
        assert page.evaluate("window.__cameraCalls") == 0
        page.locator('[data-camera-action="start"]').click()
        page.wait_for_function("document.querySelector('[data-camera-video]').videoWidth > 0")
        assert page.evaluate("window.__cameraCalls") == 1
        page.evaluate("() => { window.__cameraNode = document.querySelector('[data-scalp-camera]'); window.__track = document.querySelector('[data-camera-video]').srcObject.getVideoTracks()[0]; render(); }")
        assert page.evaluate("window.__cameraNode === document.querySelector('[data-scalp-camera]')")
        assert page.evaluate("window.__track.readyState") == "live"
        for count in (1, 2, 3):
            page.locator('[data-camera-action="capture"]').click()
            page.wait_for_function("expected => photoCount() === expected && !state.reading.size", arg=count)
            expect(page.locator(".upload-slot.filled")).to_have_count(count)
            assert page.evaluate("window.__track.readyState") == "live"
        page.locator('[data-camera-action="capture"]').click()
        expect(page.locator('#toast')).to_contain_text('최대 3장')
        expect(page.locator('.upload-slot.filled')).to_have_count(3)
        output = ROOT / 'test-results' / 'camera'
        output.mkdir(parents=True, exist_ok=True)
        for width in (320, 390, 768):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), width
            page.locator('[data-scalp-camera]').screenshot(path=str(output / f'camera-{width}.png'))
        page.locator('[data-action="next"]').click()
        page.wait_for_function("window.__track.readyState === 'ended'")
        expect(page.locator('.review-item')).to_have_count(3)
        assert not uploads, uploads
        page.locator('[data-action="back"]').click()
        page.evaluate("() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError'); }; }")
        page.locator('[data-camera-action="start"]').click()
        expect(page.locator('[data-camera-status]')).to_contain_text('권한')
        expect(page.locator('[data-camera-action="capture"]')).to_be_disabled()
        browser.close()
    print(json.dumps({"result": "PASS", "hardware": "Chrome fake camera", "checks": "permission only after click; live widget preserved through rerender; three JPEG captures; fourth photo rejected; mobile layout; tracks stopped on leaving capture step; denied permission; no photo uploads"}, ensure_ascii=False))


if __name__ == '__main__':
    main()
