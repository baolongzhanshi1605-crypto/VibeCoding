from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .models import MonitorSnapshot, QuotaWindow


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
create table if not exists task_titles (
    task_id text primary key,
    title text not null,
    observed_at integer not null
);
create table if not exists usage_snapshots (
    observed_at integer primary key,
    daily_tokens integer not null,
    weekly_tokens integer,
    daily_resets_at integer,
    weekly_started_at integer,
    weekly_resets_at integer
);
create index if not exists ix_task_snapshots_task_time
    on task_snapshots(task_id, observed_at);
create index if not exists ix_usage_snapshots_time
    on usage_snapshots(observed_at);
create table if not exists budget_observations (
    limit_id text not null,
    window_minutes integer not null,
    resets_at integer not null,
    observed_at integer not null,
    scope text not null,
    source text not null,
    used_percent real not null,
    window_tokens integer not null,
    primary key(limit_id, window_minutes, resets_at, scope, source, observed_at)
);
"""


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_recorded_at = 0
        self._last_usage_recorded_at = 0
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

    def task_titles(self) -> dict[str, str]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute("select task_id, title from task_titles").fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def record_task_titles(self, titles: dict[str, str], observed_at: int | None = None) -> None:
        values = [
            (str(task_id), " ".join(str(title).split()), int(observed_at or time.time()))
            for task_id, title in titles.items()
            if str(task_id).strip() and 0 < len(" ".join(str(title).split())) <= 128
        ]
        if not values:
            return
        with self._lock, closing(self._connect()) as connection:
            connection.executemany(
                """
                insert into task_titles(task_id, title, observed_at)
                values (?, ?, ?)
                on conflict(task_id) do update set
                    title=excluded.title,
                    observed_at=excluded.observed_at
                """,
                values,
            )
            connection.commit()

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

    def record_usage(
        self,
        observed_at: int,
        daily_tokens: int,
        weekly_tokens: int | None,
        daily_resets_at: int | None,
        weekly_started_at: int | None,
        weekly_resets_at: int | None,
        minimum_interval: int = 10,
    ) -> None:
        if observed_at - self._last_usage_recorded_at < minimum_interval:
            return
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                insert or replace into usage_snapshots
                (observed_at, daily_tokens, weekly_tokens, daily_resets_at, weekly_started_at, weekly_resets_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    observed_at,
                    daily_tokens,
                    weekly_tokens,
                    daily_resets_at,
                    weekly_started_at,
                    weekly_resets_at,
                ),
            )
            connection.commit()
        self._last_usage_recorded_at = observed_at

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

    def record_budget_observation(
        self, window: QuotaWindow, window_tokens: int, scope: str, source: str,
    ) -> None:
        if window.resets_at is None:
            return
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "insert or ignore into budget_observations values (?, ?, ?, ?, ?, ?, ?, ?)",
                (window.limit_id, window.window_minutes, window.resets_at, window.observed_at,
                 scope, source, window.used_percent, max(0, window_tokens)),
            )
            connection.commit()

    def token_budget_estimate(self, window: QuotaWindow, scope: str, source: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """select observed_at, used_percent, window_tokens from budget_observations
                where limit_id=? and window_minutes=? and resets_at=? and scope=? and source=?
                    and observed_at >= ? and observed_at <= ? order by observed_at""",
                (window.limit_id, window.window_minutes, window.resets_at, scope, source,
                 max((window.resets_at or 0) - window.window_minutes * 60, window.observed_at - 18000),
                 window.observed_at),
            ).fetchall()
        # Never join observations across a quota reset or a local counter discontinuity.
        start = 0
        for index in range(1, len(rows)):
            if rows[index][1] < rows[index - 1][1] or rows[index][2] < rows[index - 1][2]:
                start = index
        rows = rows[start:]
        percent = rows[-1][1] - rows[0][1] if rows else 0
        tokens = rows[-1][2] - rows[0][2] if rows else 0
        elapsed = rows[-1][0] - rows[0][0] if rows else 0
        ready = len(rows) >= 2 and percent >= 2 and tokens > 0 and elapsed >= 30
        return {
            "tokens_per_percent": tokens / percent if ready else None,
            "sample_count": len(rows), "consumed_percent": round(percent, 2),
            "consumed_tokens": tokens, "observed_at": rows[-1][0] if rows else None,
        }

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

    def token_history(
        self,
        lookback_seconds: int = 86_400,
        max_points: int = 360,
    ) -> list[dict[str, Any]]:
        since = int(time.time()) - lookback_seconds
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                """
                select observed_at, daily_tokens, weekly_tokens,
                       daily_resets_at, weekly_started_at, weekly_resets_at
                from usage_snapshots
                where observed_at >= ?
                order by observed_at asc
                """,
                (since,),
            ).fetchall()
        values = [
            {
                "observed_at": int(row[0]),
                "daily_tokens": int(row[1]),
                "weekly_tokens": int(row[2]) if row[2] is not None else None,
                "daily_resets_at": row[3],
                "weekly_started_at": row[4],
                "weekly_resets_at": row[5],
            }
            for row in rows
        ]
        if max_points <= 1:
            return values[-1:] if values else []
        if len(values) <= max_points:
            return values
        step = (len(values) - 1) / (max_points - 1)
        indexes = {round(index * step) for index in range(max_points)}
        return [values[index] for index in sorted(indexes)]
