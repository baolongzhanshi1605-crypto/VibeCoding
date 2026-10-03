import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong),
        ("job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("active_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "read_operations", "write_operations", "other_operations",
        "read_bytes", "write_bytes", "other_bytes",
    )]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimits), ("io", IoCounters),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


KERNEL32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
KERNEL32.CreateJobObjectW.restype = wintypes.HANDLE
KERNEL32.GetCurrentProcess.restype = wintypes.HANDLE
KERNEL32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
KERNEL32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
KERNEL32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
KERNEL32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]


def run_starter(directory: Path) -> subprocess.CompletedProcess:
    with (directory / "starter.log").open("a", encoding="utf-8") as log:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(directory / "start_codex_link.ps1")],
            cwd=directory, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15,
        )


def run_host(directory: Path, allow_breakaway: bool) -> None:
    job = KERNEL32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000 | (0x0800 if allow_breakaway else 0)
        if not KERNEL32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not KERNEL32.AssignProcessToJobObject(job, KERNEL32.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
        result = run_starter(directory)
        ready = directory / "runtime" / "listener-ready"
        deadline = time.monotonic() + 5
        while result.returncode == 0 and not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        pid_path = directory / "runtime" / "codex_link.pid"
        pid = int(pid_path.read_text(encoding="ascii").strip()) if pid_path.exists() else None
        (directory / "host-result.json").write_text(
            json.dumps({"starter_exit": result.returncode, "pid": pid}), encoding="utf-8",
        )
        deadline = time.monotonic() + 12
        while not (directory / "close-host").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        # Closing this test-owned job kills its host and any inherited children.
        KERNEL32.CloseHandle(job)


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell required")
class StartCodexLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory(prefix="launcher path-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.runtime = self.directory / "runtime"
        self.runtime.mkdir()
        shutil.copy2(PROJECT_ROOT / "start_codex_link.ps1", self.directory)
        (self.directory / "codex_link.py").write_text(
            "import os, time\nfrom pathlib import Path\n"
            "root = Path(__file__).resolve().parent / 'runtime'\n"
            "(root / 'listener-ready').write_text(str(os.getpid()), encoding='ascii')\n"
            "while True:\n    time.sleep(0.1)\n", encoding="utf-8",
        )

    def hold_listener(self, pid: int) -> int:
        handle = KERNEL32.OpenProcess(0x00101001, False, pid)
        self.assertTrue(handle, f"listener PID {pid} could not be opened")

        def cleanup() -> None:
            if self.listener_alive(handle):
                KERNEL32.TerminateProcess(handle, 0)
                KERNEL32.WaitForSingleObject(handle, 3000)
            KERNEL32.CloseHandle(handle)

        self.addCleanup(cleanup)
        return handle

    @staticmethod
    def listener_alive(handle: int) -> bool:
        code = wintypes.DWORD()
        if not KERNEL32.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259

    def launch_host(self, allow_breakaway: bool) -> tuple[subprocess.Popen, dict]:
        log = (self.directory / "host.log").open("w", encoding="utf-8")
        self.addCleanup(log.close)
        host = subprocess.Popen(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--host",
             str(self.directory), "1" if allow_breakaway else "0"],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        def cleanup() -> None:
            if host.poll() is None:
                host.kill()
            host.wait(timeout=5)

        self.addCleanup(cleanup)
        result_path = self.directory / "host-result.json"
        deadline = time.monotonic() + 20
        while not result_path.exists() and host.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(result_path.exists(), (self.directory / "host.log").read_text(encoding="utf-8"))
        return host, json.loads(result_path.read_text(encoding="utf-8"))

    def test_listener_survives_host_job_closing(self) -> None:
        host, result = self.launch_host(True)
        self.assertEqual(result["starter_exit"], 0)
        handle = self.hold_listener(result["pid"])
        (self.directory / "close-host").touch()
        host.wait(timeout=5)
        self.assertTrue(self.listener_alive(handle), "closing the host must not kill the listener")

    def test_restricted_host_reports_failure_without_false_pid(self) -> None:
        host, result = self.launch_host(False)
        if result["pid"]:
            self.hold_listener(result["pid"])
        (self.directory / "close-host").touch()
        host.wait(timeout=5)
        self.assertNotEqual(result["starter_exit"], 0, "do not claim independent startup in a restricted job")
        self.assertFalse((self.runtime / "codex_link.pid").exists())

    def test_repeated_start_keeps_the_same_listener(self) -> None:
        first = run_starter(self.directory)
        self.assertEqual(first.returncode, 0)
        pid_path = self.runtime / "codex_link.pid"
        pid = int(pid_path.read_text(encoding="ascii").strip())
        handle = self.hold_listener(pid)
        second = run_starter(self.directory)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(int(pid_path.read_text(encoding="ascii").strip()), pid)
        self.assertTrue(self.listener_alive(handle))

    def test_unrelated_live_pid_does_not_suppress_listener_start(self) -> None:
        dummy = subprocess.Popen(
            [sys.executable, "-B", "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.addCleanup(dummy.wait, 5)
        self.addCleanup(dummy.terminate)
        pid_path = self.runtime / "codex_link.pid"
        pid_path.write_text(str(dummy.pid), encoding="ascii")
        result = run_starter(self.directory)
        self.assertEqual(result.returncode, 0)
        pid = int(pid_path.read_text(encoding="ascii").strip())
        if pid != dummy.pid:
            self.hold_listener(pid)
        self.assertNotEqual(pid, dummy.pid)
        self.assertIsNone(dummy.poll(), "an unrelated process must be left alone")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--host":
        run_host(Path(sys.argv[2]), sys.argv[3] == "1")
    else:
        unittest.main()
