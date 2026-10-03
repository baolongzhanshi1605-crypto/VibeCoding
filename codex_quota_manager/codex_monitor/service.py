from __future__ import annotations

import threading
import time
from hashlib import blake2b
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .budget import BudgetPlanner
from .collector import CodexCollector
from .models import MonitorSnapshot, QuotaWindow, TaskSnapshot
from .store import SnapshotStore
from .title_source import CodexThreadTitleSource


MAX_POPUP_TASK_NAME_LENGTH = 48


def task_display_name(task: TaskSnapshot) -> str:
    manual_name = " ".join(str(task.preference.get("display_name") or "").split())
    if manual_name:
        return manual_name
    codex_name = " ".join(str(task.title or "").split())
    if codex_name and len(codex_name) <= MAX_POPUP_TASK_NAME_LENGTH:
        return codex_name
    return f"任务 {task.id[-6:]}"


class MonitorService:
    def __init__(
        self,
        runtime_dir: Path,
        codex_home: Path | None = None,
        poll_seconds: float = 1.0,
        title_source: CodexThreadTitleSource | None = None,
    ) -> None:
        self.collector = CodexCollector(codex_home=codex_home)
        self.store = SnapshotStore(runtime_dir / "manager.sqlite")
        self.title_source = title_source or CodexThreadTitleSource(self.collector.codex_home)
        self.planner = BudgetPlanner()
        self.poll_seconds = poll_seconds
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_titles = self.store.task_titles()
        self._budget_cache: dict[str, tuple[Any, int, dict[str, Any]]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.title_source.start()
        self._refresh()
        self._thread = threading.Thread(target=self._run, name="codex-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(3, self.poll_seconds + 1))
        self.title_source.stop()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            current = self._snapshot
        if current is None:
            self._refresh()
            with self._lock:
                current = self._snapshot
        return dict(current or {})

    def update_task(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]:
        current = self.store.preferences().get(task_id, {})
        priority = int(data.get("priority", current.get("priority", 3)))
        managed = bool(data.get("managed", current.get("managed", False)))
        manual = data.get("manual_cap_percent", current.get("manual_cap_percent"))
        if manual in ("", None):
            manual = None
        else:
            manual = float(manual)
        display_name = data.get("display_name", current.get("display_name"))
        if display_name is not None and not isinstance(display_name, str):
            raise ValueError("display_name must be a string")
        result = self.store.update_preference(task_id, priority, manual, managed, display_name)
        self._refresh()
        return result

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            self._refresh()

    def _refresh(self) -> None:
        try:
            raw = self.collector.collect()
            if raw.codex_home:
                self.title_source.set_codex_home(Path(raw.codex_home))
            live_titles = self.title_source.titles()
            changed_titles = {
                task_id: title
                for task_id, title in live_titles.items()
                if self._thread_titles.get(task_id) != title
            }
            if changed_titles:
                self.store.record_task_titles(changed_titles, raw.generated_at)
                self._thread_titles.update(changed_titles)
            self._apply_thread_titles(raw.tasks, self._thread_titles)
            account_windows, account_updated_at = self.title_source.quota_windows()
            raw.quota_windows, quota_source = self._select_quota_windows(
                raw.quota_windows,
                account_windows,
                account_updated_at,
            )
            self.store.record(raw)
            day_start, day_reset = self._local_day_window(raw.generated_at)
            preferences = self.store.preferences()
            task_ids = [task.id for task in raw.tasks]
            burn_rates = self.store.task_burn_rates(task_ids)
            daily_tokens = self.collector.daily_token_usage(raw.tasks, day_start)
            usage_streak = self.collector.usage_streak(raw.tasks, raw.generated_at)
            weekly_period = self._weekly_usage_period(raw.quota_windows)
            weekly_tokens = None
            weekly_start = None
            weekly_reset = None
            if weekly_period:
                weekly_start, weekly_reset = weekly_period
                weekly_tokens = self.collector.period_token_usage(raw.tasks, weekly_start)
            self.store.record_usage(
                observed_at=raw.generated_at,
                daily_tokens=daily_tokens,
                weekly_tokens=weekly_tokens,
                daily_resets_at=day_reset,
                weekly_started_at=weekly_start,
                weekly_resets_at=weekly_reset,
            )
            fresh_windows = self._fresh_quota_windows(
                raw.quota_windows,
                raw.generated_at,
                raw.latest_token_count_at,
            )
            stale_windows = [window for window in raw.quota_windows if window not in fresh_windows]
            if stale_windows:
                if fresh_windows:
                    raw.warnings.append("部分额度窗口正在等待 Codex 上报，已从预算依据中排除")
                else:
                    raw.warnings.append("额度窗口正在等待 Codex 上报，预算建议已暂停")
            plan = self.planner.plan(raw.tasks, fresh_windows, preferences, burn_rates, now=raw.generated_at)
            plan["token_budget"] = self._token_budget(raw, fresh_windows, preferences, burn_rates, quota_source)
            self._decorate(raw, preferences, burn_rates, plan)
            value = raw.to_dict()
            value["budget_plan"] = plan
            value["quota_history"] = self.store.quota_history()
            value["token_history"] = self.store.token_history()
            value["quota_source"] = {
                "source": quota_source,
                "updated_at": (
                    account_updated_at
                    if quota_source == "codex-account-rate-limits"
                    else max((window.observed_at for window in raw.quota_windows), default=None)
                ),
            }
            value["turn_display"] = self._turn_display(raw.tasks, raw.generated_at)
            value["daily_usage"] = {
                "tokens": daily_tokens,
                "resets_at": day_reset,
                "source": "rollout-midnight-delta",
            }
            value["usage_streak"] = usage_streak
            value["weekly_usage"] = {
                "tokens": weekly_tokens,
                "started_at": weekly_start,
                "resets_at": weekly_reset,
                "observed_at": next(
                    (window.observed_at for window in raw.quota_windows if window.kind == "weekly"),
                    None,
                ),
                "is_stale": next(
                    (
                        window.freshness(raw.generated_at, raw.latest_token_count_at) == "expired"
                        for window in raw.quota_windows
                        if window.kind == "weekly"
                    ),
                    True,
                ),
                "source": "rollout-weekly-window-delta" if weekly_period else "unavailable",
            }
        except Exception as exc:  # Keep the dashboard alive while Codex updates its files.
            value = {
                "generated_at": int(time.time()),
                "source": "monitor-service",
                "health": "error",
                "summary": {"active_tasks": 0, "waiting_tasks": 0, "visible_tasks": 0},
                "quota_windows": [],
                "tasks": [],
                "budget_plan": {
                    "available_percent": 0, "source": "unavailable", "allocations": {},
                    "token_budget": self.planner.plan_tokens(
                        [], [], {}, {}, {}, {}, window=None, now=int(time.time()),
                    ),
                },
                "quota_history": [],
                "token_history": [],
                "quota_source": {"source": "unavailable", "updated_at": None},
                "turn_display": {"mode": "empty", "tasks": []},
                "daily_usage": {"tokens": 0, "resets_at": None, "source": "unavailable"},
                "usage_streak": {
                    "days": 0,
                    "tokens": 0,
                    "started_at": None,
                    "current_day_tokens": 0,
                    "source": "unavailable",
                },
                "weekly_usage": {
                    "tokens": None,
                    "started_at": None,
                    "resets_at": None,
                    "observed_at": None,
                    "is_stale": True,
                    "source": "unavailable",
                },
                "warnings": [f"监测服务错误: {type(exc).__name__}: {exc}"],
            }
        value["title_sync"] = self.title_source.status()
        with self._lock:
            self._snapshot = value

    def _token_budget(
        self, raw: MonitorSnapshot, fresh_windows: list[QuotaWindow],
        preferences: dict[str, dict[str, Any]], burn_rates: dict[str, float], quota_source: str,
    ) -> dict[str, Any]:
        short = next((window for window in raw.quota_windows if window.kind == "short"), None)
        scope_text = repr((raw.codex_home, sorted((task.id, task.rollout_path, task.model) for task in raw.tasks)))
        scope = blake2b(scope_text.encode("utf-8"), digest_size=16).hexdigest()
        recent_reset = self.collector.task_period_token_data(
            raw.tasks, raw.generated_at - 18000, raw.generated_at,
        )["last_counter_reset_at"] if raw.tasks and fresh_windows else 0
        estimates: dict[str, dict[str, Any]] = {}
        usage: dict[str, int] = {}
        observed_short_tokens = 0
        for window in fresh_windows:
            if window.kind not in {"short", "weekly"} or not window.resets_at:
                continue
            if recent_reset > window.observed_at:
                estimates[window.kind] = {"tokens_per_percent": None, "reason": "counter_reset_after_report"}
                continue
            key = (window.limit_id, window.window_minutes, window.resets_at, window.observed_at,
                   window.used_percent, scope, quota_source, recent_reset)
            cached = self._budget_cache.get(window.kind)
            if cached is None or cached[0] != key:
                observed = self.collector.task_period_token_data(
                    raw.tasks, window.resets_at - window.window_minutes * 60,
                    min(raw.generated_at, window.observed_at),
                ) if raw.tasks else {"tokens": {}, "last_counter_reset_at": 0}
                observed_tokens = sum(observed["tokens"].values())
                window_scope = f"{scope}:{observed['last_counter_reset_at']}"
                self.store.record_budget_observation(window, observed_tokens, window_scope, quota_source)
                estimate = self.store.token_budget_estimate(window, window_scope, quota_source)
                cached = (key, observed_tokens, estimate)
                self._budget_cache[window.kind] = cached
            estimates[window.kind] = cached[2]
            if window.kind == "short":
                observed_short_tokens = cached[1]
        if short and short.resets_at and short.resets_at > raw.generated_at:
            usage = self.collector.task_period_token_usage(
                raw.tasks, short.resets_at - short.window_minutes * 60, raw.generated_at,
            ) if raw.tasks else {}
        unreported = max(0, sum(usage.values()) - observed_short_tokens) if short in fresh_windows else 0
        return self.planner.plan_tokens(
            raw.tasks, fresh_windows, preferences, burn_rates, usage, estimates,
            window=short, now=raw.generated_at, unreported_tokens=unreported,
            weekly_window=next((window for window in raw.quota_windows if window.kind == "weekly"), None),
        )

    @staticmethod
    def _local_day_window(now: int) -> tuple[int, int]:
        current = datetime.fromtimestamp(now)
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        reset = start + timedelta(days=1)
        return int(start.timestamp()), int(reset.timestamp())

    @staticmethod
    def _weekly_usage_period(windows: list[QuotaWindow]) -> tuple[int, int] | None:
        weekly = next(
            (window for window in windows if window.kind == "weekly" and window.resets_at),
            None,
        )
        if weekly is None:
            return None
        reset = int(weekly.resets_at or 0)
        start = reset - int(weekly.window_minutes * 60)
        return start, reset

    @staticmethod
    def _fresh_quota_windows(
        windows: list[QuotaWindow],
        now: int,
        latest_token_count_at: int | None = None,
    ) -> list[QuotaWindow]:
        return [window for window in windows if not window.is_stale(now, latest_token_count_at)]

    @staticmethod
    def _select_quota_windows(
        rollout_windows: list[QuotaWindow],
        account_windows: list[QuotaWindow],
        account_updated_at: int | None,
    ) -> tuple[list[QuotaWindow], str]:
        if account_updated_at is not None:
            return list(account_windows), "codex-account-rate-limits"
        return list(rollout_windows), "rollout-token-count"

    @staticmethod
    def _decorate(
        snapshot: MonitorSnapshot,
        preferences: dict[str, dict[str, Any]],
        burn_rates: dict[str, float],
        plan: dict[str, Any],
    ) -> None:
        allocations = plan.get("allocations", {})
        for task in snapshot.tasks:
            task.preference = preferences.get(
                task.id,
                {"priority": 3, "manual_cap_percent": None, "managed": False, "display_name": None},
            )
            task.budget = dict(allocations.get(task.id, {}))
            task.budget["token"] = plan.get("token_budget", {}).get("allocations", {}).get(task.id)
            task.burn_rate_tokens_per_minute = burn_rates.get(task.id)

    @staticmethod
    def _apply_thread_titles(tasks: list[TaskSnapshot], titles: dict[str, str]) -> None:
        for task in tasks:
            title = " ".join(str(titles.get(task.id) or "").split())
            if title:
                task.title = title

    @staticmethod
    def _turn_display(tasks: list[TaskSnapshot], now: int) -> dict[str, Any]:
        candidates = [
            task
            for task in tasks
            if task.status in {"running", "waiting"}
            or (task.turn_started_at is not None and task.turn_finished_at is not None)
        ]
        active = [task for task in candidates if task.status in {"running", "waiting"}]
        mode = "active" if active else "completed"

        if active:
            selected = list(active)
        else:
            finished = [task for task in candidates if task.turn_finished_at is not None]
            if not finished:
                return {"mode": "empty", "tasks": []}
            selected = [max(finished, key=lambda task: task.turn_finished_at or 0)]

        selected_ids = {task.id for task in selected}
        changed = True
        while changed:
            changed = False
            for task in candidates:
                if task.id in selected_ids:
                    continue
                task_start = int(task.turn_started_at or 0)
                task_end = int(task.turn_finished_at or now)
                if any(
                    task_start <= int(other.turn_finished_at or now)
                    and task_end >= int(other.turn_started_at or other.updated_at or now)
                    for other in selected
                ):
                    selected.append(task)
                    selected_ids.add(task.id)
                    changed = True

        selected.sort(
            key=lambda task: (
                task.status not in {"running", "waiting"},
                int(task.turn_started_at or 0),
                task.id,
            )
        )
        rows = []
        for task in selected:
            rows.append(
                {
                    "task_id": task.id,
                    "name": task_display_name(task),
                    "status": task.status,
                    "cumulative_tokens": task.tokens.total_tokens,
                    "turn_tokens": task.turn_tokens,
                    "started_at": task.turn_started_at,
                    "finished_at": task.turn_finished_at,
                    "token_budget": task.budget.get("token"),
                }
            )
        return {"mode": mode, "tasks": rows}
