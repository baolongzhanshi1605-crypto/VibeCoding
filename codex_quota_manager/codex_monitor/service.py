from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .budget import BudgetPlanner
from .collector import CodexCollector
from .models import MonitorSnapshot, TaskSnapshot
from .store import SnapshotStore


class MonitorService:
    def __init__(
        self,
        runtime_dir: Path,
        codex_home: Path | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        self.collector = CodexCollector(codex_home=codex_home)
        self.store = SnapshotStore(runtime_dir / "manager.sqlite")
        self.planner = BudgetPlanner()
        self.poll_seconds = poll_seconds
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._refresh()
        self._thread = threading.Thread(target=self._run, name="codex-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(3, self.poll_seconds + 1))

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
            self.store.record(raw)
            day_start, day_reset = self._local_day_window(raw.generated_at)
            preferences = self.store.preferences()
            task_ids = [task.id for task in raw.tasks]
            burn_rates = self.store.task_burn_rates(task_ids)
            daily_tokens = self.collector.daily_token_usage(raw.tasks, day_start)
            plan = self.planner.plan(raw.tasks, raw.quota_windows, preferences, burn_rates)
            self._decorate(raw, preferences, burn_rates, plan)
            value = raw.to_dict()
            value["budget_plan"] = plan
            value["quota_history"] = self.store.quota_history()
            value["turn_display"] = self._turn_display(raw.tasks, raw.generated_at)
            value["daily_usage"] = {
                "tokens": daily_tokens,
                "resets_at": day_reset,
                "source": "rollout-midnight-delta",
            }
        except Exception as exc:  # Keep the dashboard alive while Codex updates its files.
            value = {
                "generated_at": int(time.time()),
                "source": "monitor-service",
                "health": "error",
                "summary": {"active_tasks": 0, "waiting_tasks": 0, "visible_tasks": 0},
                "quota_windows": [],
                "tasks": [],
                "budget_plan": {"available_percent": 0, "source": "unavailable", "allocations": {}},
                "quota_history": [],
                "turn_display": {"mode": "empty", "tasks": []},
                "daily_usage": {"tokens": 0, "resets_at": None, "source": "unavailable"},
                "warnings": [f"监测服务错误: {type(exc).__name__}: {exc}"],
            }
        with self._lock:
            self._snapshot = value

    @staticmethod
    def _local_day_window(now: int) -> tuple[int, int]:
        current = datetime.fromtimestamp(now)
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        reset = start + timedelta(days=1)
        return int(start.timestamp()), int(reset.timestamp())

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
            task.budget = allocations.get(task.id, {})
            task.burn_rate_tokens_per_minute = burn_rates.get(task.id)

    @staticmethod
    def _turn_display(tasks: list[TaskSnapshot], now: int) -> dict[str, Any]:
        candidates = [
            task
            for task in tasks
            if task.turn_started_at is not None
            and (task.status in {"running", "waiting"} or task.turn_finished_at is not None)
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
                    and task_end >= int(other.turn_started_at or 0)
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
            display_name = str(task.preference.get("display_name") or "").strip()
            rows.append(
                {
                    "task_id": task.id,
                    "name": display_name or f"未命名任务 {task.id[-6:]}",
                    "status": task.status,
                    "cumulative_tokens": task.tokens.total_tokens,
                    "turn_tokens": task.turn_tokens,
                    "started_at": task.turn_started_at,
                    "finished_at": task.turn_finished_at,
                }
            )
        return {"mode": mode, "tasks": rows}
