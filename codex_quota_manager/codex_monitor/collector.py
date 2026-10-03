from __future__ import annotations

import json
import os
import sqlite3
import time
from bisect import bisect_left, bisect_right
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .models import MonitorSnapshot, QuotaWindow, TaskSnapshot, TokenUsage


USER_THREAD_SOURCES = {"vscode", "desktop", "app", "cli", "appServer"}


def _candidate_codex_homes() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("CODEX_HOME")
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path.home() / ".codex")

    # A portable Codex home commonly sits beside projects at the drive root.
    for source in (Path.cwd(), Path(__file__).resolve()):
        if source.anchor:
            candidates.append(Path(source.anchor) / "CodexData")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _codex_home_activity(path: Path) -> int:
    try:
        has_state_db = (path / "state_5.sqlite").is_file()
    except OSError:
        return -1
    if not has_state_db:
        return -1
    activity = -1
    for name in ("state_5.sqlite", "state_5.sqlite-wal", ".codex-global-state.json"):
        try:
            activity = max(activity, (path / name).stat().st_mtime_ns)
        except OSError:
            continue
    return activity


def _select_active_codex_home(candidates: Iterable[Path]) -> Path:
    values = list(candidates)
    if not values:
        return Path.home() / ".codex"
    return max(values, key=_codex_home_activity)


def _clean_path(value: str | None) -> str:
    return (value or "").replace("\\\\?\\", "")


def _readonly_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)


def _epoch_from_iso(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


def _tail_lines(path: Path, max_bytes: int = 2_500_000) -> Iterable[str]:
    if not path.exists():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - max_bytes)
        handle.seek(start)
        data = handle.read()
    lines = data.decode("utf-8", errors="ignore").splitlines()
    if start and lines:
        lines = lines[1:]
    return lines


@dataclass(frozen=True)
class TokenCountSample:
    observed_at: int
    total_tokens: int


@dataclass
class ParsedRollout:
    size: int = 0
    modified_ns: int = 0
    status: str = "idle"
    tokens: TokenUsage = field(default_factory=TokenUsage)
    quota_windows: list[QuotaWindow] = field(default_factory=list)
    latest_quota_at: int = 0
    latest_token_count_at: int = 0
    last_event_at: int | None = None
    pending_tool: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    turn_baseline_tokens: int | None = None
    turn_tokens: int = 0
    turn_started_at: int | None = None
    turn_finished_at: int | None = None
    token_samples: list[TokenCountSample] = field(default_factory=list)
    token_samples_size: int = 0


class CodexCollector:
    def __init__(self, codex_home: Path | None = None, max_threads: int = 80) -> None:
        self._fixed_codex_home = codex_home is not None
        self.codex_home = Path(codex_home) if codex_home is not None else _select_active_codex_home(
            _candidate_codex_homes()
        )
        self.state_db = self.codex_home / "state_5.sqlite"
        self.max_threads = max_threads
        self._rollout_cache: dict[str, ParsedRollout] = {}
        self._period_baseline_cache: dict[tuple[str, int], int] = {}

    def collect(self) -> MonitorSnapshot:
        self._refresh_codex_home()
        now = int(time.time())
        warnings: list[str] = []
        if not self.state_db.exists():
            return MonitorSnapshot(
                now,
                "unavailable",
                "error",
                [],
                [],
                [f"未找到 {self.state_db}"],
                codex_home=str(self.codex_home),
            )

        try:
            rows = self._read_threads()
        except sqlite3.Error as exc:
            return MonitorSnapshot(
                now,
                "state-db",
                "error",
                [],
                [],
                [f"读取 Codex 状态失败: {exc}"],
                codex_home=str(self.codex_home),
            )

        tasks: list[TaskSnapshot] = []
        newest_quota: list[QuotaWindow] = []
        newest_quota_at = 0
        latest_token_count_at = 0
        for row in rows:
            rollout_path = Path(_clean_path(row["rollout_path"]))
            parsed = self._parse_rollout_cached(rollout_path)
            latest_token_count_at = max(latest_token_count_at, parsed.latest_token_count_at)
            if parsed.latest_quota_at > newest_quota_at:
                newest_quota_at = parsed.latest_quota_at
                newest_quota = parsed.quota_windows

            state_tokens = int(row["tokens_used"] or 0)
            tokens = parsed.tokens
            if tokens.total_tokens == 0 and state_tokens:
                tokens = TokenUsage(total_tokens=state_tokens)

            status = self._normalized_status(parsed, now)

            tasks.append(
                TaskSnapshot(
                    id=row["id"],
                    title=row["title"],
                    cwd=_clean_path(row["cwd"]),
                    source=row["source"],
                    model=parsed.model or row["model"],
                    reasoning_effort=parsed.reasoning_effort or row["reasoning_effort"],
                    status=status,
                    updated_at=int((row["updated_at_ms"] or row["updated_at"] * 1000) / 1000),
                    tokens=tokens,
                    rollout_path=str(rollout_path),
                    created_at=int(row["created_at"] or 0) or None,
                    last_event_at=parsed.last_event_at,
                    pending_tool=parsed.pending_tool,
                    turn_tokens=parsed.turn_tokens,
                    turn_started_at=parsed.turn_started_at,
                    turn_finished_at=parsed.turn_finished_at,
                )
            )

        if not newest_quota:
            warnings.append("尚未从最近任务事件中读取到额度窗口")
        tasks.sort(key=lambda task: (task.status not in {"running", "waiting"}, -task.updated_at))
        return MonitorSnapshot(
            now,
            "codex-local-readonly",
            "ok",
            tasks,
            newest_quota,
            warnings,
            codex_home=str(self.codex_home),
            latest_token_count_at=latest_token_count_at or None,
        )

    def _refresh_codex_home(self) -> None:
        if self._fixed_codex_home:
            return
        selected = _select_active_codex_home(_candidate_codex_homes())
        if os.path.normcase(os.path.abspath(selected)) == os.path.normcase(os.path.abspath(self.codex_home)):
            return
        self.codex_home = selected
        self.state_db = selected / "state_5.sqlite"
        self._rollout_cache.clear()
        self._period_baseline_cache.clear()

    def daily_token_usage(self, tasks: list[TaskSnapshot], day_start_epoch: int) -> int:
        return self.period_token_usage(tasks, day_start_epoch)

    def task_period_token_usage(
        self, tasks: list[TaskSnapshot], period_start_epoch: int, period_end_epoch: int | None = None,
    ) -> dict[str, int]:
        return self.task_period_token_data(tasks, period_start_epoch, period_end_epoch)["tokens"]

    def task_period_token_data(
        self, tasks: list[TaskSnapshot], period_start_epoch: int, period_end_epoch: int | None = None,
    ) -> dict[str, Any]:
        values: dict[str, int] = {}
        last_reset = 0
        for task in tasks:
            samples = self._parse_rollout_cached(Path(task.rollout_path)).token_samples
            start = bisect_left(samples, period_start_epoch, key=lambda sample: sample.observed_at)
            end = bisect_right(samples, period_end_epoch, key=lambda sample: sample.observed_at) if period_end_epoch is not None else len(samples)
            previous = samples[start - 1].total_tokens if start else 0
            total = 0
            for sample in samples[start:end]:
                if sample.total_tokens < previous:
                    last_reset = max(last_reset, sample.observed_at)
                    previous = 0
                increment = max(0, sample.total_tokens - previous)
                previous = sample.total_tokens
                total += increment
            values[task.id] = total
        return {"tokens": values, "last_counter_reset_at": last_reset}

    def period_token_usage(self, tasks: list[TaskSnapshot], period_start_epoch: int) -> int:
        total = 0
        for task in tasks:
            baseline = self._token_baseline_at(Path(task.rollout_path), period_start_epoch)
            total += max(0, int(task.tokens.total_tokens) - baseline)
        return total

    def usage_streak(self, tasks: list[TaskSnapshot], now_epoch: int) -> dict[str, int | str | None]:
        daily_tokens = self._calendar_token_deltas(tasks)
        today = datetime.fromtimestamp(now_epoch).date()
        days = 0
        tokens = 0
        cursor = today
        while daily_tokens.get(cursor, 0) > 0:
            days += 1
            tokens += daily_tokens[cursor]
            cursor -= timedelta(days=1)
        started_at = int(datetime.combine(cursor + timedelta(days=1), datetime.min.time()).timestamp()) if days else None
        return {
            "days": days,
            "tokens": tokens,
            "started_at": started_at,
            "current_day_tokens": daily_tokens.get(today, 0),
            "source": "rollout-calendar-delta",
        }

    def _calendar_token_deltas(self, tasks: list[TaskSnapshot]) -> dict[object, int]:
        daily_tokens: dict[object, int] = {}
        for task in tasks:
            samples = self._parse_rollout_cached(Path(task.rollout_path)).token_samples
            previous_total: int | None = None
            for sample in samples:
                if previous_total is None:
                    increment = sample.total_tokens
                else:
                    increment = max(0, sample.total_tokens - previous_total)
                previous_total = sample.total_tokens
                if increment <= 0:
                    continue
                day = datetime.fromtimestamp(sample.observed_at).date()
                daily_tokens[day] = daily_tokens.get(day, 0) + increment
        return daily_tokens

    def _token_baseline_at(self, path: Path, period_start_epoch: int) -> int:
        key = (str(path).lower(), period_start_epoch)
        cached = self._period_baseline_cache.get(key)
        if cached is not None:
            return cached

        baseline = 0
        try:
            lines = path.open("r", encoding="utf-8", errors="ignore")
        except OSError:
            self._period_baseline_cache[key] = baseline
            return baseline

        with lines:
            for line in lines:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = _epoch_from_iso(item.get("timestamp"))
                if timestamp is not None and timestamp >= period_start_epoch:
                    break
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                if item.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                usage = TokenUsage.from_payload(info.get("total_token_usage"))
                baseline = max(baseline, usage.total_tokens)

        self._period_baseline_cache[key] = baseline
        return baseline

    @staticmethod
    def _normalized_status(parsed: ParsedRollout, now: int) -> str:
        if (
            parsed.status in {"running", "paused"}
            and not parsed.pending_tool
            and parsed.last_event_at
            and now - parsed.last_event_at > 300
        ):
            return "idle"
        return parsed.status

    def _read_threads(self) -> list[sqlite3.Row]:
        with closing(_readonly_connection(self.state_db)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                select id, rollout_path, created_at, updated_at, source, cwd, title,
                       tokens_used, model, reasoning_effort, updated_at_ms
                from threads
                where archived = 0
                order by coalesce(updated_at_ms, updated_at * 1000) desc
                limit ?
                """,
                (self.max_threads,),
            ).fetchall()
        return [row for row in rows if row["source"] in USER_THREAD_SOURCES]

    def _parse_rollout_cached(self, path: Path) -> ParsedRollout:
        key = str(path).lower()
        try:
            stat = path.stat()
        except OSError:
            return ParsedRollout(status="unavailable")
        cached = self._rollout_cache.get(key)
        if cached and cached.size == stat.st_size and cached.modified_ns == stat.st_mtime_ns:
            return cached
        parsed = self._parse_rollout(path)
        if cached:
            if not parsed.latest_quota_at:
                parsed.latest_quota_at = cached.latest_quota_at
                parsed.quota_windows = list(cached.quota_windows)
            if not parsed.latest_token_count_at:
                parsed.latest_token_count_at = cached.latest_token_count_at
        if parsed.turn_started_at is None and cached and cached.turn_started_at is not None:
            if (
                parsed.status == "idle"
                and parsed.turn_finished_at is None
                and cached.status in {"running", "waiting"}
            ):
                parsed.status = cached.status
            parsed.turn_started_at = cached.turn_started_at
            parsed.turn_baseline_tokens = cached.turn_baseline_tokens
            parsed.turn_finished_at = parsed.turn_finished_at or cached.turn_finished_at
            baseline = parsed.turn_baseline_tokens or 0
            parsed.turn_tokens = max(0, parsed.tokens.total_tokens - baseline)
        elif parsed.turn_started_at is None and stat.st_mtime >= time.time() - 86_400:
            parsed = self._parse_rollout(path, full=True)
        self._refresh_token_samples(path, parsed, cached, stat.st_size, stat.st_mtime_ns)
        parsed.size = stat.st_size
        parsed.modified_ns = stat.st_mtime_ns
        self._rollout_cache[key] = parsed
        return parsed

    def _refresh_token_samples(
        self,
        path: Path,
        parsed: ParsedRollout,
        cached: ParsedRollout | None,
        size: int,
        modified_ns: int,
    ) -> None:
        if cached is None or size < cached.token_samples_size or (
            size == cached.token_samples_size and modified_ns != cached.modified_ns
        ):
            parsed.token_samples = self._token_samples_from_file(path)
        elif size > cached.token_samples_size:
            start = max(0, cached.token_samples_size - 4096)
            parsed.token_samples = self._merge_token_samples(
                cached.token_samples,
                self._token_samples_from_file(path, start),
            )
        else:
            parsed.token_samples = list(cached.token_samples)
        parsed.token_samples_size = size

    @staticmethod
    def _merge_token_samples(
        current: list[TokenCountSample],
        appended: list[TokenCountSample],
    ) -> list[TokenCountSample]:
        result: list[TokenCountSample] = []
        seen: set[tuple[int, int]] = set()
        for sample in sorted([*current, *appended], key=lambda value: value.observed_at):
            key = (sample.observed_at, sample.total_tokens)
            if key not in seen:
                seen.add(key)
                result.append(sample)
        return result

    @staticmethod
    def _token_samples_from_file(path: Path, start: int = 0) -> list[TokenCountSample]:
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            return []
        lines = data.decode("utf-8", errors="ignore").splitlines()
        if start and lines:
            lines = lines[1:]
        samples: list[TokenCountSample] = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("type") != "event_msg":
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            observed_at = _epoch_from_iso(item.get("timestamp"))
            if observed_at is None:
                continue
            info = payload.get("info") or {}
            total_tokens = TokenUsage.from_payload(info.get("total_token_usage")).total_tokens
            samples.append(TokenCountSample(observed_at, total_tokens))
        return samples

    def _parse_rollout(self, path: Path, full: bool = False) -> ParsedRollout:
        parsed = ParsedRollout()
        task_event: str | None = None
        pending_tools: dict[str, str] = {}
        pending_permissions: dict[str, str] = {}
        latest_total = 0
        awaiting_first_turn_count = False

        lines: Iterable[str]
        if full:
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                lines = []
        else:
            lines = _tail_lines(path)

        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = _epoch_from_iso(item.get("timestamp"))
            if timestamp:
                parsed.last_event_at = max(parsed.last_event_at or 0, timestamp)
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue

            item_type = item.get("type")
            payload_type = payload.get("type")
            if item_type == "turn_context":
                parsed.model = payload.get("model") or parsed.model
                parsed.reasoning_effort = payload.get("reasoning_effort") or parsed.reasoning_effort

            if item_type == "event_msg" and payload_type in {"task_started", "task_complete", "turn_aborted"}:
                task_event = str(payload_type)
                if payload_type == "task_started":
                    parsed.turn_baseline_tokens = latest_total
                    parsed.turn_tokens = 0
                    parsed.turn_started_at = timestamp
                    parsed.turn_finished_at = None
                    awaiting_first_turn_count = True
                if payload_type in {"task_complete", "turn_aborted"}:
                    parsed.turn_finished_at = timestamp
                    pending_tools.clear()
                    pending_permissions.clear()

            if item_type == "event_msg" and payload_type == "token_count":
                parsed.latest_token_count_at = timestamp or int(time.time())
                info = payload.get("info") or {}
                usage = TokenUsage.from_payload(info.get("total_token_usage"))
                last_usage = TokenUsage.from_payload(info.get("last_token_usage"))
                parsed.tokens = usage
                latest_total = usage.total_tokens
                if parsed.turn_started_at is not None:
                    if awaiting_first_turn_count:
                        candidate = max(0, usage.total_tokens - last_usage.total_tokens)
                        if last_usage.total_tokens:
                            parsed.turn_baseline_tokens = candidate
                        awaiting_first_turn_count = False
                    baseline = parsed.turn_baseline_tokens or 0
                    parsed.turn_tokens = max(0, usage.total_tokens - baseline)
                windows = self._quota_windows(payload.get("rate_limits"), timestamp or int(time.time()))
                if windows:
                    parsed.quota_windows = windows
                    parsed.latest_quota_at = timestamp or int(time.time())

            call_id = payload.get("call_id")
            if payload_type == "function_call" and call_id:
                name = str(payload.get("name") or "tool")
                arguments = str(payload.get("arguments") or "")
                pending_tools[str(call_id)] = name
                if "require_escalated" in arguments or "request_plugin_install" in arguments:
                    pending_permissions[str(call_id)] = name
            elif payload_type == "function_call_output" and call_id:
                pending_tools.pop(str(call_id), None)
                pending_permissions.pop(str(call_id), None)

        if pending_permissions:
            parsed.status = "waiting"
            parsed.pending_tool = next(reversed(pending_permissions.values()))
        elif task_event == "task_started" or pending_tools:
            parsed.status = "running"
            if pending_tools:
                parsed.pending_tool = next(reversed(pending_tools.values()))
        elif task_event == "turn_aborted":
            parsed.status = "paused"
        elif task_event == "task_complete":
            parsed.status = "completed"
        else:
            parsed.status = "idle"
        return parsed

    @staticmethod
    def _quota_windows(rate_limits: Any, observed_at: int) -> list[QuotaWindow]:
        if not isinstance(rate_limits, dict):
            return []
        limit_id = str(rate_limits.get("limit_id") or "codex")
        result: list[QuotaWindow] = []
        for bucket_name in ("primary", "secondary"):
            bucket = rate_limits.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            duration = int(bucket.get("window_minutes") or bucket.get("windowDurationMins") or 0)
            if duration <= 0:
                continue
            result.append(
                QuotaWindow(
                    limit_id=limit_id,
                    window_minutes=duration,
                    used_percent=float(bucket.get("used_percent") or bucket.get("usedPercent") or 0),
                    resets_at=int(bucket.get("resets_at") or bucket.get("resetsAt") or 0) or None,
                    observed_at=observed_at,
                )
            )
        result.sort(key=lambda window: window.window_minutes)
        return result
