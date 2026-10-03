"""Loopback-only, in-memory budget data for browser and native UI checks."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import DashboardHandler, DashboardServer
from codex_monitor.budget import BudgetPlanner
from codex_monitor.models import MonitorSnapshot, QuotaWindow, TaskSnapshot, TokenUsage
from codex_monitor.service import MonitorService


class BudgetFixture:
    def __init__(self) -> None:
        self.preferences = {}
        self.scenario = "ready"

    def update_task(self, task_id, payload):
        preference = self.preferences.setdefault(task_id, {})
        preference.update(payload)
        return preference

    def snapshot(self):
        now = int(time.time())
        short = QuotaWindow("fixture", 300, 60, now + 3600, now)
        weekly = QuotaWindow("fixture", 10080, 20, now + 50 * 3600, now)
        if self.scenario == "zero":
            short = QuotaWindow("fixture", 300, 99, now + 3600, now)
        tasks = [
            TaskSnapshot(
                id=task_id, title=title, cwd="F:\\Codex_project", source="fixture",
                model="test-model", reasoning_effort=None, status=status,
                updated_at=now, tokens=TokenUsage(total_tokens=total), rollout_path="fixture.jsonl",
                turn_tokens=100_000, turn_started_at=now - 600,
                turn_finished_at=now - 10 if status == "completed" else None,
            )
            for task_id, title, status, total in [
                ("parallel-a", "并行任务一（测试数据）", "running", 4_100_000),
                ("parallel-b", "并行任务二（测试数据）", "running", 2_200_000),
                ("waiting", "等待确认任务（测试数据）", "waiting", 9_000_000),
                ("completed", "已结束任务（测试数据）", "completed", 3_000_000),
                ("idle", "空闲任务（测试数据）", "idle", 0),
            ]
        ]
        rates = {"parallel-a": 200_000, "parallel-b": 100_000, "waiting": 0}
        if self.scenario == "many":
            for index in range(4):
                tasks.append(TaskSnapshot(
                    id=f"extra-{index}", title=f"额外活动任务 {index + 1}（测试数据）",
                    cwd="F:\\Codex_project", source="fixture", model="test-model",
                    reasoning_effort=None, status="running", updated_at=now,
                    tokens=TokenUsage(total_tokens=100_000), rollout_path="fixture.jsonl",
                ))
                rates[f"extra-{index}"] = 100_000
        if self.scenario == "unknown_rate":
            rates = {}
        if self.scenario == "after_reset":
            rates = {"parallel-a": 1, "parallel-b": 1}
        windows = [short, weekly]
        raw = MonitorSnapshot(now, "ui-test-fixture", "ok", tasks, windows)
        planner = BudgetPlanner()
        plan = planner.plan(tasks, windows, self.preferences, rates, now=now)
        estimates = {"short": {"tokens_per_percent": 100_000}, "weekly": {"tokens_per_percent": 750_000}}
        plan["token_budget"] = planner.plan_tokens(
            tasks, [] if self.scenario == "stale" else windows, self.preferences, rates,
            {"parallel-a": 400_000, "parallel-b": 200_000, "waiting": 80_000},
            {} if self.scenario == "calibrating" else estimates, window=short, now=now,
        )
        MonitorService._decorate(raw, self.preferences, rates, plan)
        result = raw.to_dict()
        result.update(
            budget_plan=plan, turn_display=MonitorService._turn_display(tasks, now),
            daily_usage={"tokens": 290_123_456, "resets_at": now + 9000},
            weekly_usage={"tokens": 900_000_000, "is_stale": False},
            usage_streak={"days": 4, "tokens": 600_000_000, "current_day_tokens": 290_123_456},
            quota_history=[], token_history=[], title_sync={"source": "fixture"},
        )
        return result


class FixtureHandler(DashboardHandler):
    def do_POST(self):
        if self.path.startswith("/fixture/scenario/"):
            self.dashboard.service.scenario = self.path.rsplit("/", 1)[-1]
            self._json({"ok": True})
        else:
            super().do_POST()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    server = DashboardServer(("127.0.0.1", args.port), BudgetFixture())
    server.RequestHandlerClass = FixtureHandler
    print("Budget fixture ready", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
