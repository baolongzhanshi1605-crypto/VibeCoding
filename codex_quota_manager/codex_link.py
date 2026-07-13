from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes
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
        return []
    entries: list[tuple[str, int, int]] = []
    item = PROCESSENTRY32W()
    item.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if not KERNEL32.Process32FirstW(snapshot, ctypes.byref(item)):
            return entries
        while True:
            entries.append((item.szExeFile.lower(), int(item.th32ProcessID), int(item.th32ParentProcessID)))
            if not KERNEL32.Process32NextW(snapshot, ctypes.byref(item)):
                break
    finally:
        KERNEL32.CloseHandle(snapshot)
    return entries


def is_codex_desktop_tree(entries: list[tuple[str, int, int]]) -> bool:
    names_by_pid = {pid: name for name, pid, _parent in entries}
    return any(
        name == "codex.exe" and names_by_pid.get(parent_pid) == "chatgpt.exe"
        for name, _pid, parent_pid in entries
    )


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
        with urllib.request.urlopen(HEALTH_URL, timeout=0.8) as response:
            return response.status == 200
    except OSError:
        return False


def run_script(path: Path, timeout: int = 30) -> None:
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
        check=False,
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
    if WIDGET_DISMISSED_PATH.exists() or read_pid(WIDGET_PID_PATH):
        return
    logging.info("starting desktop widget")
    subprocess.Popen(
        [str(pythonw_executable()), str(WIDGET_PATH)],
        cwd=PROJECT_ROOT,
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )


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


def main() -> int:
    configure_logging()
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    LINK_PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    previous: bool | None = None
    last_health_check = 0.0
    logging.info("Codex lifecycle link started")
    try:
        while True:
            active = codex_desktop_running()
            now = time.monotonic()
            if active and (previous is not True or now - last_health_check >= 5):
                ensure_dashboard()
                if dashboard_running():
                    ensure_widget()
                last_health_check = now
            elif not active and previous is not False:
                stop_monitoring()
            if active != previous:
                logging.info("Codex desktop active=%s", active)
            previous = active
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
