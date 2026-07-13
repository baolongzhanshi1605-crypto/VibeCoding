from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .models import MonitorSnapshot


SCHEMA = """
pragma journal_mode = wal;
create table if not exists task_preferences (
    task_id text primary key,
    priority integer not null default 3 check(priority between 1 and 5),
    manual_cap_percent real,
    managed integer not null default 0 check(managed in (0, 1)),
    display_name text,
    updated_at integer not null
);
create table if not exists quota_snapshots (
    observed_at integer not null,
    limit_id text not null,
    window_minutes integer not null,
    used_percent real not null,
    resets_at integer,
    primary key(observed_at, limit_id, window_minutes)
);
create table if not exists task_snapshots (
    observed_at integer not null,
    task_id text not null,
    total_tokens integer not null,
    status text not null,
    primary key(observed_at, task_id)
);
create index if not exists ix_task_snapshots_task_time
    on task_snapshots(task_id, observed_at);
"""


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_recorded_at = 0
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
            columns = {row[1] for row in connection.execute("pragma table_info(task_preferences)")}
            if "display_name" not in columns:
                connection.execute("alter table task_preferences add column display_name text")
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=3)

    def preferences(self) -> dict[str, dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "select task_id, priority, manual_cap_percent, managed, display_name, updated_at from task_preferences"
            ).fetchall()
        return {
            row[0]: {
                "priority": int(row[1]),
                "manual_cap_percent": row[2],
                "managed": bool(row[3]),
                "display_name": row[4],
                "updated_at": int(row[5]),
            }
            for row in rows
        }

    def update_preference(
        self,
        task_id: str,
        priority: int,
        manual_cap_percent: float | None,
        managed: bool,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= priority <= 5:
            raise ValueError("priority must be between 1 and 5")
        if manual_cap_percent is not None and not 0 <= manual_cap_percent <= 100:
            raise ValueError("manual_cap_percent must be between 0 and 100")
        if display_name is not None:
            display_name = display_name.strip() or None
        if display_name is not None and (len(display_name) > 32 or any(ord(char) < 32 for char in display_name)):
            raise ValueError("display_name must be 32 printable characters or fewer")
        updated_at = int(time.time())
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                insert into task_preferences(task_id, priority, manual_cap_percent, managed, display_name, updated_at)
                values (?, ?, ?, ?, ?, ?)
                on conflict(task_id) do update set
                    priority=excluded.priority,
                    manual_cap_percent=excluded.manual_cap_percent,
                    managed=excluded.managed,
                    display_name=excluded.display_name,
                    updated_at=excluded.updated_at
                """,
                (task_id, priority, manual_cap_percent, int(managed), display_name, updated_at),
            )
            connection.commit()
        return {
            "priority": priority,
            "manual_cap_percent": manual_cap_percent,
            "managed": managed,
            "display_name": display_name,
            "updated_at": updated_at,
        }

    def record(self, snapshot: MonitorSnapshot, minimum_interval: int = 10) -> None:
        if snapshot.generated_at - self._last_recorded_at < minimum_interval:
            return
        with self._lock, closing(self._connect()) as connection:
            for window in snapshot.quota_windows:
                connection.execute(
                    """
                    insert or ignore into quota_snapshots
                    (observed_at, limit_id, window_minutes, used_percent, resets_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.generated_at,
                        window.limit_id,
                        window.window_minutes,
                        window.used_percent,
                        window.resets_at,
                    ),
                )
            for task in snapshot.tasks:
                connection.execute(
                    """
                    insert or ignore into task_snapshots
                    (observed_at, task_id, total_tokens, status)
                    values (?, ?, ?, ?)
                    """,
                    (snapshot.generated_at, task.id, task.tokens.total_tokens, task.status),
                )
            connection.commit()
        self._last_recorded_at = snapshot.generated_at

    def task_burn_rates(self, task_ids: list[str], lookback_seconds: int = 900) -> dict[str, float]:
        if not task_ids:
            return {}
        since = int(time.time()) - lookback_seconds
        rates: dict[str, float] = {}
        with self._lock, closing(self._connect()) as connection:
            for task_id in task_ids:
                rows = connection.execute(
                    """
                    select observed_at, total_tokens
                    from task_snapshots
                    where task_id = ? and observed_at >= ?
                    order by observed_at asc
                    """,
                    (task_id, since),
                ).fetchall()
                if len(rows) < 2:
                    continue
                elapsed_minutes = max((rows[-1][0] - rows[0][0]) / 60.0, 0.1)
                delta = max(0, rows[-1][1] - rows[0][1])
                rates[task_id] = delta / elapsed_minutes
        return rates

    def quota_history(
        self,
        lookback_seconds: int = 86_400,
        max_points_per_window: int = 360,
    ) -> list[dict[str, Any]]:
        since = int(time.time()) - lookback_seconds
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                select observed_at, window_minutes, used_percent, resets_at
                from quota_snapshots
                where observed_at >= ?
                order by observed_at asc
                """,
                (since,),
            ).fetchall()
        values = [
            {
                "observed_at": int(row[0]),
                "window_minutes": int(row[1]),
                "used_percent": float(row[2]),
                "resets_at": row[3],
            }
            for row in rows
        ]
        if max_points_per_window <= 1:
            return values[-1:] if values else []

        grouped: dict[int, list[dict[str, Any]]] = {}
        for value in values:
            grouped.setdefault(value["window_minutes"], []).append(value)

        sampled: list[dict[str, Any]] = []
        for points in grouped.values():
            if len(points) <= max_points_per_window:
                sampled.extend(points)
                continue
            step = (len(points) - 1) / (max_points_per_window - 1)
            indexes = {round(index * step) for index in range(max_points_per_window)}
            sampled.extend(points[index] for index in sorted(indexes))
        sampled.sort(key=lambda item: (item["observed_at"], item["window_minutes"]))
        return sampled
