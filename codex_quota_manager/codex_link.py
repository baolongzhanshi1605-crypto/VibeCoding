from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes
from http.client import HTTPException
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
LINK_PID_PATH = RUNTIME_ROOT / "codex_link.pid"
WIDGET_PID_PATH = RUNTIME_ROOT / "desktop_widget.pid"
WIDGET_DISMISSED_PATH = RUNTIME_ROOT / "desktop_widget.dismissed"
START_DASHBOARD = PROJECT_ROOT / "start_dashboard.ps1"
STOP_DASHBOARD = PROJECT_ROOT / "stop_dashboard.ps1"
WIDGET_PATH = PROJECT_ROOT / "desktop_widget.py"
HEALTH_URL = "http://127.0.0.1:8790/health"
CREATE_NO_WINDOW = 0x08000000
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
KERNEL32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
KERNEL32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
KERNEL32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
KERNEL32.Process32FirstW.restype = wintypes.BOOL
KERNEL32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
KERNEL32.Process32NextW.restype = wintypes.BOOL
KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
KERNEL32.TerminateProcess.restype = wintypes.BOOL
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL32.CloseHandle.restype = wintypes.BOOL


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def process_entries() -> list[tuple[str, int, int]]:
    snapshot = KERNEL32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    entries: list[tuple[str, int, int]] = []
    item = PROCESSENTRY32W()
    item.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if not KERNEL32.Process32FirstW(snapshot, ctypes.byref(item)):
            error = ctypes.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES
                raise ctypes.WinError(error)
            return entries
        while True:
            entries.append((item.szExeFile.lower(), int(item.th32ProcessID), int(item.th32ParentProcessID)))
            if not KERNEL32.Process32NextW(snapshot, ctypes.byref(item)):
                break
    finally:
        KERNEL32.CloseHandle(snapshot)
    return entries


def codex_desktop_pids(entries: list[tuple[str, int, int]]) -> set[int]:
    names_by_pid = {pid: name for name, pid, _parent in entries}
    return {
        parent_pid
        for name, _pid, parent_pid in entries
        if name == "codex.exe" and names_by_pid.get(parent_pid) == "chatgpt.exe"
    }


def is_codex_desktop_tree(entries: list[tuple[str, int, int]]) -> bool:
    return bool(codex_desktop_pids(entries))


def codex_desktop_running() -> bool:
    return is_codex_desktop_tree(process_entries())


def pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    process = KERNEL32.OpenProcess(0x00100000, False, pid)
    if not process:
        return False
    KERNEL32.CloseHandle(process)
    return True


def read_pid(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return value if pid_running(value) else None


def terminate_pid(path: Path) -> None:
    pid = read_pid(path)
    if pid:
        process = KERNEL32.OpenProcess(0x0001, False, pid)
        if process:
            KERNEL32.TerminateProcess(process, 0)
            KERNEL32.CloseHandle(process)
    path.unlink(missing_ok=True)


def dashboard_running() -> bool:
    try:
        with LOCAL_HTTP.open(HEALTH_URL, timeout=2) as response:
            return response.status == 200
    except (OSError, HTTPException):
        return False


def run_script(path: Path, timeout: int = 60) -> None:
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path),
        ],
        cwd=PROJECT_ROOT,
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=True,
    )


def pythonw_executable() -> Path:
    executable = Path(sys.executable)
    candidate = executable.with_name("pythonw.exe")
    return candidate if candidate.exists() else executable


def ensure_dashboard() -> None:
    if dashboard_running():
        return
    logging.info("starting dashboard")
    run_script(START_DASHBOARD)


def ensure_widget() -> None:
    if read_pid(WIDGET_PID_PATH):
        return
    logging.info("starting desktop widget")
    process = subprocess.Popen(
        [str(pythonw_executable()), str(WIDGET_PATH)],
        cwd=PROJECT_ROOT,
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )
    WIDGET_PID_PATH.write_text(str(process.pid), encoding="ascii")


def stop_monitoring() -> None:
    logging.info("stopping desktop widget and dashboard")
    terminate_pid(WIDGET_PID_PATH)
    WIDGET_DISMISSED_PATH.unlink(missing_ok=True)
    run_script(STOP_DASHBOARD, timeout=15)


def configure_logging() -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=RUNTIME_ROOT / "codex_link.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


class CodexExitGuard:
    def __init__(self, grace_seconds: float = 5) -> None:
        self.grace_seconds = grace_seconds
        self.missing_since: float | None = None

    def should_exit(self, active: bool | None, now: float) -> bool:
        if active is not False:
            self.missing_since = None
            return False
        if self.missing_since is None:
            self.missing_since = now
        return now - self.missing_since >= self.grace_seconds


class LifecycleController:
    def __init__(self) -> None:
        self.exit_guard = CodexExitGuard()
        self.previous: bool | None = None
        self.next_health_check = 0.0
        self.cleanup_complete = False

    def tick(self) -> None:
        try:
            now = time.monotonic()
            try:
                active = codex_desktop_running()
            except OSError:
                self.exit_guard.should_exit(None, now)
                raise
            exit_due = self.exit_guard.should_exit(active, now)
            if active != self.previous:
                logging.info("Codex desktop active=%s", active)
                if active:
                    self.next_health_check = now
                self.previous = active
            if active:
                self.cleanup_complete = False
                if now >= self.next_health_check:
                    self.next_health_check = now + 5
                    ensure_dashboard()
                    if dashboard_running():
                        ensure_widget()
            elif exit_due and not self.cleanup_complete and now >= self.next_health_check:
                self.next_health_check = now + 5
                stop_monitoring()
                self.cleanup_complete = True
        except Exception:
            logging.exception("lifecycle operation failed; retrying on the next check")


def main() -> int:
    configure_logging()
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    LINK_PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    controller = LifecycleController()
    logging.info("Codex lifecycle link started")
    try:
        while True:
            controller.tick()
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.exception("lifecycle link failed")
        return 1
    finally:
        LINK_PID_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
