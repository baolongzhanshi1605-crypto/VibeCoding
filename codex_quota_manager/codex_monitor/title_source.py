from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .models import QuotaWindow


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_TITLE_LENGTH = 128


def _normalized_title(value: object) -> str | None:
    title = " ".join(str(value or "").split())
    if not title or len(title) > MAX_TITLE_LENGTH:
        return None
    return title


def _modified_at(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _codex_executable_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("CODEX_MONITOR_CODEX_EXE")
    if configured:
        candidates.append(Path(configured))

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        bin_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
        try:
            installed = [path for path in bin_root.glob("*/codex.exe") if path.is_file()]
        except OSError:
            installed = []
        installed.sort(key=_modified_at, reverse=True)
        candidates.extend(installed)

    for name in ("codex.exe", "codex"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


class CodexThreadTitleSource:
    """Read sidebar names and account quotas through a read-only app-server session."""

    def __init__(
        self,
        codex_home: Path,
        refresh_seconds: float = 2.0,
        retry_seconds: float = 5.0,
        request_timeout: float = 15.0,
        quota_request_timeout: float = 5.0,
        max_threads: int = 100,
    ) -> None:
        self.codex_home = Path(codex_home)
        self.refresh_seconds = refresh_seconds
        self.retry_seconds = retry_seconds
        self.request_timeout = request_timeout
        self.quota_request_timeout = quota_request_timeout
        self.max_threads = max_threads
        self._lock = threading.Lock()
        self._titles: dict[str, str] = {}
        self._updated_at: int | None = None
        self._health = "stopped"
        self._last_error: str | None = None
        self._quota_windows: list[QuotaWindow] = []
        self._quota_updated_at: int | None = None
        self._quota_health = "stopped"
        self._quota_last_error: str | None = None
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._request_sequence = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._restart.clear()
        with self._lock:
            self._health = "starting"
            self._quota_health = "starting"
        self._thread = threading.Thread(target=self._run, name="codex-title-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._restart.set()
        self._terminate_current_process()
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            self._health = "stopped"
            self._quota_health = "stopped"

    def set_codex_home(self, codex_home: Path) -> None:
        value = Path(codex_home)
        with self._lock:
            changed = os.path.normcase(os.path.abspath(value)) != os.path.normcase(
                os.path.abspath(self.codex_home)
            )
            if changed:
                self.codex_home = value
                self._titles = {}
                self._health = "starting"
                self._quota_windows = []
                self._quota_updated_at = None
                self._quota_health = "starting"
        if changed:
            self._restart.set()
            self._terminate_current_process()

    def titles(self) -> dict[str, str]:
        with self._lock:
            return dict(self._titles)

    def quota_windows(
        self,
        max_age_seconds: float | None = None,
        now: float | None = None,
    ) -> tuple[list[QuotaWindow], int | None]:
        current = time.time() if now is None else now
        with self._lock:
            updated_at = self._quota_updated_at
            windows = list(self._quota_windows)
        if updated_at is None:
            return [], None
        if max_age_seconds is not None and current - updated_at > max_age_seconds:
            return [], None
        return windows, updated_at

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "source": "codex-app-server-readonly",
                "health": self._health,
                "updated_at": self._updated_at,
                "title_count": len(self._titles),
                "last_error": self._last_error,
                "quota_health": self._quota_health,
                "quota_updated_at": self._quota_updated_at,
                "quota_last_error": self._quota_last_error,
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            self._restart.clear()
            process: subprocess.Popen[str] | None = None
            try:
                process, messages = self._connect()
                while not self._stop.is_set() and not self._restart.is_set():
                    self._refresh_account_quota(process, messages)
                    result = self._request(
                        process,
                        messages,
                        "thread/list",
                        {
                            "limit": self.max_threads,
                            "archived": False,
                            "sortKey": "updated_at",
                            "sortDirection": "desc",
                            "useStateDbOnly": True,
                        },
                    )
                    titles = self._extract_titles(result)
                    with self._lock:
                        self._titles = titles
                        self._updated_at = int(time.time())
                        self._health = "ok"
                        self._last_error = None
                    if self._restart.wait(self.refresh_seconds):
                        break
            except Exception as exc:
                if not self._stop.is_set() and not self._restart.is_set():
                    with self._lock:
                        self._health = "degraded"
                        self._last_error = f"{type(exc).__name__}: {exc}"[:240]
                        self._quota_health = "degraded"
                        self._quota_last_error = f"{type(exc).__name__}: {exc}"[:240]
            finally:
                self._terminate_process(process)
            if not self._stop.is_set() and not self._restart.is_set():
                self._stop.wait(self.retry_seconds)

    def _connect(self) -> tuple[subprocess.Popen[str], queue.Queue[dict[str, Any]]]:
        errors: list[str] = []
        for executable in _codex_executable_candidates():
            if self._stop.is_set() or self._restart.is_set():
                raise RuntimeError("title sync interrupted")
            process: subprocess.Popen[str] | None = None
            try:
                env = dict(os.environ)
                with self._lock:
                    env["CODEX_HOME"] = str(self.codex_home)
                process = subprocess.Popen(
                    [str(executable), "app-server", "--stdio"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                    creationflags=CREATE_NO_WINDOW,
                )
                with self._lock:
                    self._process = process
                messages: queue.Queue[dict[str, Any]] = queue.Queue()
                threading.Thread(
                    target=self._read_messages,
                    args=(process, messages),
                    name="codex-title-protocol-reader",
                    daemon=True,
                ).start()
                result = self._request(
                    process,
                    messages,
                    "initialize",
                    {
                        "clientInfo": {"name": "codex-quota-manager", "version": "0.1.0"},
                        "capabilities": {
                            "optOutNotificationMethods": [
                                "thread/started",
                                "thread/status/changed",
                            ]
                        },
                    },
                )
                if not isinstance(result, dict):
                    raise RuntimeError("invalid initialize response")
                self._notify(process, "initialized")
                return process, messages
            except (OSError, RuntimeError, TimeoutError) as exc:
                errors.append(f"{executable.name}: {exc}")
                self._terminate_process(process)
        detail = "; ".join(errors) or "Codex executable not found"
        raise RuntimeError(detail)

    def _request(
        self,
        process: subprocess.Popen[str],
        messages: queue.Queue[dict[str, Any]],
        method: str,
        params: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self._request_sequence += 1
        request_id = f"quota-{self._request_sequence}"
        self._write(process, {"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + (self.request_timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"app-server exited with code {process.returncode}")
            remaining = max(0.05, deadline - time.monotonic())
            try:
                message = messages.get(timeout=min(0.5, remaining))
            except queue.Empty:
                continue
            if message.get("id") != request_id:
                continue
            if message.get("error") is not None:
                raise RuntimeError(str(message["error"]))
            result = message.get("result")
            return result if isinstance(result, dict) else {}
        raise TimeoutError(f"{method} timed out")

    def _refresh_account_quota(
        self,
        process: subprocess.Popen[str],
        messages: queue.Queue[dict[str, Any]],
    ) -> None:
        try:
            result = self._request(
                process,
                messages,
                "account/rateLimits/read",
                {},
                timeout=self.quota_request_timeout,
            )
            observed_at = int(time.time())
            windows = self._extract_quota_windows(result, observed_at)
        except (RuntimeError, TimeoutError) as exc:
            with self._lock:
                self._quota_health = "degraded"
                self._quota_last_error = f"{type(exc).__name__}: {exc}"[:240]
            return

        if not windows:
            with self._lock:
                self._quota_health = "degraded"
                self._quota_last_error = "account/rateLimits/read returned no quota windows"
            return

        with self._lock:
            self._quota_windows = windows
            self._quota_updated_at = observed_at
            self._quota_health = "ok"
            self._quota_last_error = None

    def _notify(self, process: subprocess.Popen[str], method: str) -> None:
        self._write(process, {"method": method})

    @staticmethod
    def _write(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
        if process.stdin is None:
            raise RuntimeError("app-server stdin is unavailable")
        process.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
        process.stdin.flush()

    @staticmethod
    def _read_messages(
        process: subprocess.Popen[str],
        messages: queue.Queue[dict[str, Any]],
    ) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                messages.put(message)

    @staticmethod
    def _extract_titles(result: dict[str, Any]) -> dict[str, str]:
        rows = result.get("data")
        if not isinstance(rows, list):
            return {}
        titles: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            task_id = str(row.get("id") or "").strip()
            title = _normalized_title(row.get("name"))
            if task_id and title:
                titles[task_id] = title
        return titles

    @staticmethod
    def _extract_quota_windows(result: dict[str, Any], observed_at: int) -> list[QuotaWindow]:
        snapshot = result.get("rateLimits")
        if not isinstance(snapshot, dict):
            by_limit_id = result.get("rateLimitsByLimitId")
            if isinstance(by_limit_id, dict):
                candidate = by_limit_id.get("codex")
                if not isinstance(candidate, dict):
                    candidate = next(
                        (value for value in by_limit_id.values() if isinstance(value, dict)),
                        None,
                    )
                snapshot = candidate
        if not isinstance(snapshot, dict):
            return []

        limit_id = str(snapshot.get("limitId") or "codex")
        windows: list[QuotaWindow] = []
        for bucket_name in ("primary", "secondary"):
            bucket = snapshot.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            try:
                duration = int(bucket.get("windowDurationMins") or 0)
                used_percent = float(bucket.get("usedPercent") or 0)
                resets_at = int(bucket.get("resetsAt") or 0) or None
            except (TypeError, ValueError):
                continue
            if duration <= 0:
                continue
            windows.append(
                QuotaWindow(
                    limit_id=limit_id,
                    window_minutes=duration,
                    used_percent=used_percent,
                    resets_at=resets_at,
                    observed_at=observed_at,
                )
            )
        windows.sort(key=lambda window: window.window_minutes)
        return windows

    def _terminate_current_process(self) -> None:
        with self._lock:
            process = self._process
        self._terminate_process(process)

    def _terminate_process(self, process: subprocess.Popen[str] | None) -> None:
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        with self._lock:
            if self._process is process:
                self._process = None
