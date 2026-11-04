"""Check launcher ownership and readiness with isolated HTTP endpoints only.

No real model process, browser, account database, or existing port is used.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from launcher import LaunchCancelled, LaunchError, ServiceController, WindowsInstanceLock
from runtime_identity import SERVICE_ID, installation_id


class HealthEndpoint:
    """Serve scripted responses on an OS-assigned loopback port."""

    def __init__(self, *responses):
        self.responses = deque(responses)
        self.lock = threading.Lock()
        self.requests = []
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with endpoint.lock:
                    endpoint.requests.append(self.path)
                    response = endpoint.responses[0]
                    if len(endpoint.responses) > 1:
                        endpoint.responses.popleft()
                if isinstance(response, dict):
                    status, body, content_type = 200, json.dumps(response).encode(), "application/json"
                else:
                    status, body, content_type = response
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True,
        )
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="scalp-launcher-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # An implementation mistake must never start the real four-model server.
        popen = patch("launcher.subprocess.Popen", side_effect=AssertionError("Unexpected real process launch"))
        popen.start()
        self.addCleanup(popen.stop)

    def health(self, status="ready", **fields):
        return {
            "application": SERVICE_ID,
            "installation_id": installation_id(self.root),
            "status": status,
            "models": [],
            **fields,
        }

    def endpoint(self, *responses):
        endpoint = HealthEndpoint(*responses)
        self.addCleanup(endpoint.close)
        return endpoint

    def controller(self, endpoint, timeout=2):
        return ServiceController(self.root, port=endpoint.port, timeout=timeout)

    def test_installation_identity_is_stable_and_distinguishes_project_folders(self):
        identity = installation_id(self.root)
        self.assertRegex(identity, r"^[0-9a-f]{24}$")
        self.assertEqual(identity, installation_id(self.root / "."))
        self.assertNotEqual(identity, installation_id(self.root / "different-project"))

    def test_probe_returns_none_when_nothing_is_listening(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        controller = ServiceController(self.root, port=port, timeout=0.1)
        self.assertIsNone(controller.probe())
        self.assertFalse(controller.owns_server)

    def test_matching_ready_server_is_reused_without_starting_or_stopping_it(self):
        endpoint = self.endpoint(self.health())
        controller = self.controller(endpoint)
        with patch.object(controller, "_spawn") as spawn:
            result = controller.start()
            spawn.assert_not_called()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(controller.url, f"http://127.0.0.1:{endpoint.port}")
        self.assertFalse(controller.owns_server)
        controller.stop()
        self.assertEqual(controller.probe()["status"], "ready")
        self.assertEqual(set(endpoint.requests), {"/api/health"})

    def test_owned_server_binding_during_http_timeout_remains_in_startup(self):
        controller = ServiceController(self.root, port=8765, timeout=0.1)
        controller.process = Mock(pid=987654, poll=Mock(return_value=None))
        failures = [urllib.error.URLError(TimeoutError("not listening yet")), TimeoutError("still binding")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with (
                    patch.object(controller._http, "open", side_effect=failure),
                    patch.object(controller, "_port_in_use", return_value=True),
                ):
                    self.assertIsNone(controller.probe())
        self.assertTrue(controller.owns_server)

    def test_external_occupied_port_after_http_timeout_is_still_a_conflict(self):
        controller = ServiceController(self.root, port=8765, timeout=0.1)
        failures = [urllib.error.URLError(TimeoutError("unrelated server")), TimeoutError("unrelated server")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with (
                    patch.object(controller._http, "open", side_effect=failure),
                    patch.object(controller, "_port_in_use", return_value=True),
                    self.assertRaises(LaunchError),
                ):
                    controller.probe()
        self.assertFalse(controller.owns_server)

    def test_loading_existing_server_is_waited_for_until_ready(self):
        endpoint = self.endpoint(self.health("loading"), self.health("loading"), self.health())
        controller = self.controller(endpoint)
        with patch.object(controller, "_spawn") as spawn:
            result = controller.start()
            spawn.assert_not_called()
        self.assertEqual(result["status"], "ready")
        self.assertGreaterEqual(len(endpoint.requests), 3)
        self.assertFalse(controller.owns_server)

    def test_different_service_is_rejected_without_spawn(self):
        endpoint = self.endpoint(self.health(application="another-service"))
        controller = self.controller(endpoint)
        with patch.object(controller, "_spawn") as spawn, self.assertRaises(LaunchError):
            controller.start()
        spawn.assert_not_called()
        self.assertFalse(controller.owns_server)

    def test_same_service_in_another_project_is_rejected(self):
        endpoint = self.endpoint(self.health(installation_id=installation_id(self.root / "other")))
        with self.assertRaises(LaunchError):
            self.controller(endpoint).probe()

    def test_legacy_endpoint_without_identity_is_not_reused(self):
        endpoint = self.endpoint({"status": "ready", "models": []})
        with self.assertRaises(LaunchError):
            self.controller(endpoint).probe()

    def test_malformed_health_is_not_treated_as_a_free_port(self):
        cases = [
            (200, b"<html>different website</html>", "text/html"),
            (200, b"[1, 2, 3]", "application/json"),
            (404, b"not a health endpoint", "text/plain"),
        ]
        for response in cases:
            with self.subTest(response=response):
                endpoint = self.endpoint(response)
                controller = self.controller(endpoint)
                with patch.object(controller, "_spawn") as spawn, self.assertRaises(LaunchError):
                    controller.start()
                spawn.assert_not_called()

    def test_occupied_non_http_port_is_rejected_without_starting_a_server(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.05)
        port = listener.getsockname()[1]
        stopped = threading.Event()

        def unrelated_protocol():
            while not stopped.is_set():
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with connection:
                    try:
                        connection.settimeout(0.2)
                        connection.recv(4096)
                        connection.sendall(b"SSH-2.0-unrelated-service\r\n")
                    except OSError:
                        pass

        thread = threading.Thread(target=unrelated_protocol, daemon=True)
        thread.start()
        controller = ServiceController(self.root, port=port, timeout=0.1)
        try:
            with patch.object(controller, "_spawn") as spawn, self.assertRaises(LaunchError):
                controller.start()
            spawn.assert_not_called()
            self.assertFalse(controller.owns_server)
        finally:
            stopped.set()
            listener.close()
            thread.join(timeout=1)

    def test_http_proxy_settings_do_not_intercept_local_health(self):
        endpoint = self.endpoint(self.health())
        environment = {
            "HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1", "all_proxy": "http://127.0.0.1:1",
            "NO_PROXY": "", "no_proxy": "",
        }
        with patch.dict(os.environ, environment):
            self.assertEqual(self.controller(endpoint).probe()["status"], "ready")

    def test_existing_server_model_error_is_reported_and_server_remains_running(self):
        endpoint = self.endpoint(self.health("error", message="Model preparation failed"))
        controller = self.controller(endpoint)
        with patch.object(controller, "_spawn") as spawn, self.assertRaises(LaunchError):
            controller.start()
        spawn.assert_not_called()
        self.assertEqual(controller.probe()["status"], "error")
        self.assertFalse(controller.owns_server)

    def test_cancelled_before_start_does_not_spawn(self):
        endpoint = self.endpoint(self.health())
        controller = self.controller(endpoint)
        controller.stop()
        with patch.object(controller, "_spawn") as spawn, self.assertRaises(LaunchCancelled):
            controller.start()
        spawn.assert_not_called()
        self.assertFalse(controller.owns_server)

    def test_owned_server_model_error_cleans_up_owned_process(self):
        endpoint = self.endpoint(self.health("error", message="Model preparation failed"))
        controller = self.controller(endpoint)
        fake_process = Mock(pid=987654, poll=Mock(return_value=None))

        def spawn_owned():
            controller.process = fake_process

        with (
            patch.object(controller, "probe", side_effect=[None, self.health("error", message="Failed")]),
            patch.object(controller, "_spawn", side_effect=spawn_owned) as spawn,
            patch.object(controller, "_stop_owned") as stop_owned,
            self.assertRaises(LaunchError),
        ):
            controller.start()
        spawn.assert_called_once()
        self.assertTrue(stop_owned.called)

    def test_owned_server_startup_timeout_cleans_up_owned_process(self):
        endpoint = self.endpoint(self.health("loading"))
        controller = self.controller(endpoint, timeout=0.05)
        fake_process = Mock(pid=987654, poll=Mock(return_value=None))
        calls = 0

        def probe():
            nonlocal calls
            calls += 1
            return None if calls == 1 else self.health("loading")

        def spawn_owned():
            controller.process = fake_process

        with (
            patch.object(controller, "probe", side_effect=probe),
            patch.object(controller, "_spawn", side_effect=spawn_owned) as spawn,
            patch.object(controller, "_stop_owned") as stop_owned,
            self.assertRaises(LaunchError),
        ):
            controller.start()
        spawn.assert_called_once()
        self.assertTrue(stop_owned.called)

    def test_cancellation_during_process_creation_still_cleans_up(self):
        endpoint = self.endpoint(self.health("loading"))
        controller = self.controller(endpoint)
        entered_spawn = threading.Event()
        finish_spawn = threading.Event()
        errors = []

        def spawn_owned():
            entered_spawn.set()
            if not finish_spawn.wait(timeout=3):
                raise AssertionError("Test did not release the fake process creation")
            controller.process = Mock(pid=987654, poll=Mock(return_value=None))

        def start():
            try:
                controller.start()
            except BaseException as exc:
                errors.append(exc)

        with (
            patch.object(controller, "probe", return_value=None),
            patch.object(controller, "_spawn", side_effect=spawn_owned),
            patch.object(controller, "_stop_owned") as stop_owned,
        ):
            starter = threading.Thread(target=start, daemon=True)
            stopper = threading.Thread(target=controller.stop, daemon=True)
            starter.start()
            try:
                self.assertTrue(entered_spawn.wait(timeout=1))
                stopper.start()
                self.assertTrue(controller.cancel.wait(timeout=1))
            finally:
                finish_spawn.set()
                starter.join(timeout=2)
                if stopper.ident is not None:
                    stopper.join(timeout=2)
            self.assertFalse(starter.is_alive())
            self.assertFalse(stopper.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], LaunchCancelled)
            self.assertTrue(stop_owned.called)

    @unittest.skipUnless(os.name == "nt", "Windows named mutex")
    def test_duplicate_launcher_mutex_is_released_when_window_closes(self):
        first = WindowsInstanceLock(self.root, 8765)
        second = WindowsInstanceLock(self.root, 8765)
        third = WindowsInstanceLock(self.root, 8765)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.addCleanup(third.close)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        second.close()
        first.close()
        self.assertTrue(third.acquire())


if __name__ == "__main__":
    unittest.main()
