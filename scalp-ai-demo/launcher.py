"""Windows service launcher. Keeps network/model work off the Tk event loop."""

from __future__ import annotations

import argparse
import ctypes
import http.client
import json
import logging
import os
import queue
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from runtime_identity import SERVICE_ID, installation_id

ROOT = Path(__file__).resolve().parent
TITLE = "두피 관리 서비스 실행"


class LaunchError(RuntimeError):
    pass


class LaunchCancelled(LaunchError):
    pass


class ServiceController:
    def __init__(self, root: Path, port: int = 8000, timeout: float = 300):
        self.root = Path(root).resolve()
        self.port = port
        self.timeout = timeout
        self.url = f"http://127.0.0.1:{port}"
        self.process = None
        self.cancel = threading.Event()
        self._process_lock = threading.Lock()
        # Never send a local readiness request through a configured HTTP proxy.
        self._http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @property
    def owns_server(self):
        return self.process is not None and self.process.poll() is None

    def _port_in_use(self):
        with socket.socket() as connection:
            connection.settimeout(0.5)
            return connection.connect_ex(("127.0.0.1", self.port)) == 0

    def probe(self):
        conflict = "실행 주소를 다른 프로그램이 사용하고 있어요. 기존 실행 창을 확인한 뒤 다시 시도해 주세요."
        try:
            with self._http.open(f"{self.url}/api/health", timeout=1.5) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise LaunchError(conflict)
            health = json.loads(raw)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise LaunchError(conflict) from exc
        except http.client.HTTPException as exc:
            raise LaunchError(conflict) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # A connection attempt can begin before our child binds the port,
            # then fail after it has bound it. Keep waiting on our own child.
            if self.owns_server:
                return None
            if self._port_in_use():
                raise LaunchError(conflict) from exc
            return None
        except (ValueError, UnicodeError) as exc:
            raise LaunchError(conflict) from exc
        if (not isinstance(health, dict)
                or health.get("application") != SERVICE_ID
                or health.get("installation_id") != installation_id(self.root)):
            raise LaunchError(conflict)
        return health

    def _spawn(self):
        with self._process_lock:
            if self.cancel.is_set():
                raise LaunchCancelled()
            python = self.root / ".venv" / "Scripts" / "python.exe"
            if not python.is_file():
                raise LaunchError("실행 환경이 아직 설치되지 않았어요. 먼저 install.cmd를 실행해 주세요.")
            runtime = self.root / ".runtime"
            runtime.mkdir(exist_ok=True)
            environment = os.environ.copy()
            environment["PYTHONUTF8"] = "1"
            environment["PYTHONUNBUFFERED"] = "1"
            with (runtime / "server-launcher.log").open("a", encoding="utf-8") as output:
                output.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} :{self.port} ---\n")
                output.flush()
                self.process = subprocess.Popen(
                    [str(python), "-X", "utf8", "-u", str(self.root / "server.py"),
                     "--host", "127.0.0.1", "--port", str(self.port)],
                    cwd=self.root, env=environment,
                    stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            logging.info("Started owned server PID %s, port %s", self.process.pid, self.port)

    def start(self, report=lambda message: None):
        try:
            if self.cancel.is_set():
                raise LaunchCancelled()
            report("실행 상태를 확인하고 있어요.")
            health = self.probe()
            if health is None:
                self._spawn()
            deadline = time.monotonic() + self.timeout
            while True:
                if self.cancel.is_set():
                    raise LaunchCancelled()
                if self.process is not None and self.process.poll() is not None:
                    raise LaunchError("서비스가 시작 도중 종료됐어요. 실행 기록에서 원인을 확인해 주세요.")
                if health is not None:
                    status = health.get("status")
                    if status == "ready":
                        return health
                    if status == "error":
                        raise LaunchError("AI 분석 모델을 준비하지 못했어요. 모델 파일과 실행 기록을 확인해 주세요.")
                    if status != "loading":
                        raise LaunchError("서비스 상태를 확인하지 못했어요. 실행 기록을 확인해 주세요.")
                    models = health.get("models") or []
                    ready = sum(bool(model.get("ready")) for model in models if isinstance(model, dict))
                    detail = f" ({ready}/{len(models)})" if models else ""
                    report(f"AI 분석 모델을 준비하고 있어요.{detail} 잠시만 기다려 주세요.")
                else:
                    report("웹 서비스를 시작하고 있어요. 잠시만 기다려 주세요.")
                if time.monotonic() >= deadline:
                    raise LaunchError("서비스 준비가 오래 걸리고 있어요. 실행 기록을 확인한 뒤 다시 시도해 주세요.")
                if self.cancel.wait(0.5):
                    raise LaunchCancelled()
                health = self.probe()
        except BaseException:
            self._stop_owned()
            raise

    def _stop_owned(self):
        with self._process_lock:
            process = self.process
            if process is None:
                return
            if process.poll() is None:
                if os.name == "nt":
                    # The venv executable may launch a child interpreter. Stop the
                    # exact Popen tree, never a name match or a PID from a file.
                    result = subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW, timeout=15,
                    )
                    if result.returncode and process.poll() is None:
                        raise LaunchError("서비스 종료를 확인하지 못했어요. 실행 창에서 다시 종료해 주세요.")
                else:
                    process.terminate()
                process.wait(timeout=10)
            logging.info("Owned server PID %s stopped", process.pid)
            self.process = None

    def stop(self):
        self.cancel.set()
        self._stop_owned()


class WindowsInstanceLock:
    """One control window per installation/port. The OS releases the mutex on exit."""
    def __init__(self, root, port):
        self.name = f"Local\\ScalpWeb-{installation_id(root)}-{port}"
        self.handle = None
        self.kernel = None

    def acquire(self):
        if os.name != "nt":
            return True
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateMutexW(None, False, self.name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            self.close()
            return False
        return True

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def focus_existing(title):
    if os.name != "nt":
        return
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    window = user.FindWindowW(None, title)
    if window:
        user.ShowWindow(window, 9)  # SW_RESTORE
        user.SetForegroundWindow(window)


class LauncherWindow:
    def __init__(self, window, port, auto_browser=True):
        import tkinter as tk
        from tkinter import ttk
        self.window = window
        self.port = port
        self.auto_browser = auto_browser
        self.events = queue.Queue()
        self.controller = None
        self.closing = False
        self.ready = False
        window.title(TITLE if port == 8000 else f"{TITLE} ({port})")
        window.geometry("570x370")
        window.minsize(570, 370)
        window.resizable(False, False)
        window.configure(bg="#f4f8f6")
        window.option_add("*Font", ("맑은 고딕", 10))
        frame = tk.Frame(window, bg="white", padx=30, pady=26)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(frame, text="딥러닝 기반 AI 두피 관리 서비스", bg="white", fg="#174f43",
                 font=("맑은 고딕", 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(frame, text="사진으로 살펴보는 나의 두피 상태", bg="white", fg="#62736c",
                 anchor="w").pack(fill="x", pady=(6, 22))
        self.status = tk.StringVar(value="웹 서비스를 준비하고 있어요.")
        tk.Label(frame, textvariable=self.status, bg="white", fg="#213f35", anchor="w",
                 wraplength=470, justify="left", height=3).pack(fill="x")
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(5, 12))
        self.note = tk.StringVar(value="준비가 끝나면 브라우저가 자동으로 열려요.")
        tk.Label(frame, textvariable=self.note, bg="white", fg="#62736c", wraplength=470,
                 anchor="w", justify="left", height=2).pack(fill="x")
        actions = tk.Frame(frame, bg="white")
        actions.pack(fill="x", pady=(16, 0))
        self.primary = tk.Button(actions, text="웹 열기", command=self.open_web,
                                 bg="#176852", fg="white", activebackground="#124f40",
                                 activeforeground="white", relief="flat", padx=22, pady=8,
                                 cursor="hand2", state="disabled")
        self.primary.pack(side="left")
        self.exit_button = tk.Button(actions, text="종료", command=self.close,
                                     relief="flat", bg="#edf3f0", fg="#274c3f", padx=18, pady=8)
        self.exit_button.pack(side="left", padx=10)
        self.log_button = tk.Button(actions, text="실행 기록 보기", command=self.open_log,
                                    relief="flat", bg="white", fg="#62736c", cursor="hand2")
        self.log_button.pack(side="right")
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.after(100, self.drain)
        self.launch()

    def launch(self):
        self.ready = False
        self.controller = ServiceController(ROOT, self.port)
        self.primary.configure(state="disabled", text="웹 열기", command=self.open_web)
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.note.set("준비가 끝나면 브라우저가 자동으로 열려요.")
        def work():
            try:
                self.controller.start(lambda value: self.events.put(("status", value)))
            except LaunchCancelled:
                return
            except Exception as exc:
                logging.exception("Launcher start failed")
                message = str(exc) if isinstance(exc, LaunchError) else "서비스를 시작하지 못했어요. 실행 기록을 확인해 주세요."
                self.events.put(("error", message))
            else:
                self.events.put(("ready", None))
                # Detect an unexpected shutdown without blocking the window.
                while not self.controller.cancel.wait(3):
                    try:
                        health = self.controller.probe()
                        if health is None or health.get("status") != "ready":
                            raise LaunchError("웹 서비스 연결이 끊겼어요. 다시 시도해 주세요.")
                    except Exception:
                        logging.exception("Running service became unavailable")
                        try:
                            self.controller.stop()
                        except Exception:
                            logging.exception("Cleanup after service failure failed")
                        self.events.put(("error", "웹 서비스 연결이 끊겼어요. 실행 기록을 확인해 주세요."))
                        return
        threading.Thread(target=work, daemon=True).start()

    def drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "closed":
                    self.window.destroy()
                    return
                if self.closing:
                    if kind == "close_error":
                        self.closing = False
                        self.status.set(value)
                        self.exit_button.configure(state="normal", text="종료 다시 시도")
                    continue
                if kind == "status":
                    self.status.set(value)
                elif kind == "error":
                    self.progress.stop()
                    self.status.set(value)
                    self.note.set("문제를 해결한 뒤 다시 시도할 수 있어요.")
                    self.ready = False
                    self.primary.configure(state="normal", text="다시 시도", command=self.launch)
                    if self.controller.owns_server:
                        # Preserve ownership if cleanup failed; do not replace
                        # the controller and abandon a still-running child.
                        self.primary.configure(text="서비스 종료", command=self.close)
                elif kind == "ready":
                    self.ready = True
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=100)
                    self.status.set("준비가 끝났어요. 웹에서 두피 분석을 시작해 보세요.")
                    if self.controller.owns_server:
                        self.note.set("이 창을 닫으면 웹 서비스도 함께 종료돼요.")
                        self.exit_button.configure(text="서비스 종료")
                    else:
                        self.note.set("이미 실행 중인 서비스를 열었어요. 이 창을 닫아도 기존 서비스는 유지돼요.")
                        self.exit_button.configure(text="실행 창 닫기")
                    self.primary.configure(state="normal")
                    if self.auto_browser:
                        self.open_web()
        except queue.Empty:
            pass
        self.window.after(100, self.drain)

    def open_web(self):
        if not self.ready:
            return
        def work():
            try:
                if not webbrowser.open(self.controller.url, new=2):
                    self.events.put(("status", f"브라우저에서 {self.controller.url} 주소를 열어 주세요."))
            except Exception:
                logging.exception("Browser open failed")
                self.events.put(("status", f"브라우저에서 {self.controller.url} 주소를 열어 주세요."))
        threading.Thread(target=work, daemon=True).start()

    def open_log(self):
        path = ROOT / ".runtime" / "server-launcher.log"
        if not path.is_file():
            path = ROOT / ".runtime" / "launcher.log"
        if path.is_file() and os.name == "nt":
            os.startfile(path)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.status.set("서비스를 종료하고 있어요. 잠시만 기다려 주세요.")
        self.primary.configure(state="disabled")
        self.exit_button.configure(state="disabled")
        def work():
            try:
                self.controller.stop()
            except Exception:
                logging.exception("Launcher stop failed")
                self.events.put(("close_error", "서비스 종료를 확인하지 못했어요. 종료를 다시 시도해 주세요."))
            else:
                self.events.put(("closed", None))
        threading.Thread(target=work, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open a browser (verification).")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    logging.basicConfig(filename=runtime / "launcher.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    lock = WindowsInstanceLock(ROOT, args.port)
    title = TITLE if args.port == 8000 else f"{TITLE} ({args.port})"
    if not lock.acquire():
        # Allow the first process a moment to create its window during rapid double-clicks.
        time.sleep(0.4)
        focus_existing(title)
        return
    ui = None
    try:
        import tkinter as tk
        window = tk.Tk()
        ui = LauncherWindow(window, args.port, auto_browser=not args.no_browser)
        window.mainloop()
    except Exception:
        logging.exception("Launcher window failed")
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None,
                "실행 창을 열지 못했어요. .runtime 폴더의 launcher.log를 확인해 주세요.", TITLE, 0x10)
        raise
    finally:
        try:
            if ui is not None and ui.controller is not None:
                ui.controller.stop()
        finally:
            lock.close()


if __name__ == "__main__":
    main()
