import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from codex_monitor.models import MonitorSnapshot, QuotaWindow, TaskSnapshot, TokenUsage
from codex_monitor.service import MonitorService, task_display_name
from codex_monitor.title_source import CodexThreadTitleSource


class TurnDisplayTests(unittest.TestCase):
    def test_active_task_without_turn_timestamp_still_receives_popup_budget(self) -> None:
        task = self._task("new", "running", 100, None, 0)
        task.turn_started_at = None
        task.budget = {"token": {"window_used_tokens": 10, "remaining_tokens": 100}}
        result = MonitorService._turn_display([task], now=110)
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["token_budget"]["remaining_tokens"], 100)

    @staticmethod
    def _task(
        task_id: str,
        status: str,
        started_at: int,
        finished_at: int | None,
        turn_tokens: int,
    ) -> TaskSnapshot:
        task = TaskSnapshot(
            id=task_id,
            title="hidden conversation title",
            cwd="C:/repo",
            source="desktop",
            model=None,
            reasoning_effort=None,
            status=status,
            updated_at=finished_at or started_at,
            tokens=TokenUsage(total_tokens=turn_tokens + 10_000),
            rollout_path=f"C:/{task_id}.jsonl",
            turn_tokens=turn_tokens,
            turn_started_at=started_at,
            turn_finished_at=finished_at,
        )
        task.preference = {"display_name": f"project-{task_id}"}
        return task

    def test_parallel_completed_task_remains_with_running_batch(self) -> None:
        running = self._task("running", "running", 100, None, 400)
        parallel = self._task("parallel", "completed", 110, 120, 200)
        old = self._task("old", "completed", 10, 20, 100)

        result = MonitorService._turn_display([running, parallel, old], now=130)

        self.assertEqual(result["mode"], "active")
        self.assertEqual([row["task_id"] for row in result["tasks"]], ["running", "parallel"])
        self.assertEqual([row["turn_tokens"] for row in result["tasks"]], [400, 200])

    def test_new_non_overlapping_task_replaces_completed_batch(self) -> None:
        current = self._task("current", "running", 300, None, 50)
        previous = self._task("previous", "completed", 100, 200, 900)
        stale = self._task("stale", "idle", 10, None, 800)

        result = MonitorService._turn_display([current, previous, stale], now=310)

        self.assertEqual([row["task_id"] for row in result["tasks"]], ["current"])

    def test_parallel_completed_batch_is_retained(self) -> None:
        first = self._task("first", "completed", 100, 200, 500)
        second = self._task("second", "completed", 150, 170, 300)
        old = self._task("old", "completed", 10, 20, 100)

        result = MonitorService._turn_display([first, second, old], now=250)

        self.assertEqual(result["mode"], "completed")
        self.assertEqual({row["task_id"] for row in result["tasks"]}, {"first", "second"})

    def test_codex_sidebar_title_is_used_without_local_override(self) -> None:
        task = self._task("019f7564-4ad8-7630-bff6-99c44181a22e", "running", 100, None, 50)
        task.title = "维护VPN"
        task.preference = {"display_name": None}

        result = MonitorService._turn_display([task], now=110)

        self.assertEqual(result["tasks"][0]["name"], "维护VPN")

    def test_live_title_replaces_stale_database_title(self) -> None:
        task = self._task("019f4f97-7882-7283-bb1d-5880a6110381", "running", 100, None, 50)
        task.title = "很长的初始任务提示"

        MonitorService._apply_thread_titles([task], {task.id: "商品筛选"})

        self.assertEqual(task.title, "商品筛选")

    def test_local_monitor_name_keeps_highest_priority(self) -> None:
        task = self._task("task-override", "running", 100, None, 50)
        task.title = "Codex 名称"
        task.preference = {"display_name": "本地监控名称"}

        self.assertEqual(task_display_name(task), "本地监控名称")

    def test_long_prompt_is_not_exposed_in_popup(self) -> None:
        task = self._task("019f4f97-7882-7283-bb1d-5880a6110381", "running", 100, None, 50)
        task.title = "这是一段不应该直接显示在悬浮窗里的用户对话内容" * 5
        task.preference = {"display_name": None}

        self.assertEqual(task_display_name(task), "任务 110381")

    def test_weekly_usage_period_matches_reported_quota_window(self) -> None:
        reset = 2_000_000_000
        windows = [
            QuotaWindow("codex", 300, 10, reset - 500_000, reset - 600_000),
            QuotaWindow("codex", 10_080, 40, reset, reset - 100),
        ]

        self.assertEqual(
            MonitorService._weekly_usage_period(windows),
            (reset - 10_080 * 60, reset),
        )

    def test_weekly_usage_period_is_unavailable_without_weekly_reset(self) -> None:
        windows = [QuotaWindow("codex", 10_080, 40, None, 100)]

        self.assertIsNone(MonitorService._weekly_usage_period(windows))

    def test_idle_quota_window_remains_current_even_when_report_is_old(self) -> None:
        snapshot = MonitorSnapshot(
            generated_at=2_000,
            source="test",
            health="ok",
            tasks=[],
            quota_windows=[QuotaWindow("codex", 10_080, 8, 3_000, 1_000)],
            latest_token_count_at=1_000,
        )

        window = snapshot.to_dict()["quota_windows"][0]

        self.assertEqual(window["age_seconds"], 1_000)
        self.assertFalse(window["is_stale"])
        self.assertEqual(window["freshness"], "current")

    def test_quota_waits_for_report_after_new_token_activity(self) -> None:
        window = QuotaWindow("codex", 10_080, 8, 9_000, 1_000)

        value = window.to_dict(now=2_000, latest_token_count_at=1_500)

        self.assertTrue(value["is_stale"])
        self.assertEqual(value["freshness"], "awaiting_report")

    def test_quota_is_expired_after_window_reset(self) -> None:
        window = QuotaWindow("codex", 10_080, 8, 1_900, 1_000)

        value = window.to_dict(now=2_000, latest_token_count_at=1_000)

        self.assertTrue(value["is_stale"])
        self.assertEqual(value["freshness"], "expired")

    def test_stale_quota_windows_are_excluded_from_budget_input(self) -> None:
        windows = [
            QuotaWindow("codex", 300, 10, 3_000, 1_500),
            QuotaWindow("codex", 10_080, 8, 9_000, 500),
        ]

        fresh = MonitorService._fresh_quota_windows(windows, now=2_000, latest_token_count_at=1_000)

        self.assertEqual([window.kind for window in fresh], ["short"])

    def test_live_account_quota_replaces_pre_reset_rollout_value(self) -> None:
        rollout = [QuotaWindow("codex", 10_080, 100, 9_000, 1_000)]
        account = [QuotaWindow("codex", 10_080, 0, 10_000, 2_000)]

        windows, source = MonitorService._select_quota_windows(rollout, account, 2_000)

        self.assertEqual(source, "codex-account-rate-limits")
        self.assertEqual(windows[0].remaining_percent, 100)

    def test_rollout_quota_remains_fallback_when_account_read_is_unavailable(self) -> None:
        rollout = [QuotaWindow("codex", 10_080, 42, 9_000, 1_000)]

        windows, source = MonitorService._select_quota_windows(rollout, [], None)

        self.assertEqual(source, "rollout-token-count")
        self.assertEqual(windows, rollout)

    def test_retained_account_quota_does_not_jump_back_to_old_rollout_value(self) -> None:
        source = CodexThreadTitleSource(".")
        account = QuotaWindow("codex", 10_080, 1, 10_000, 100)
        rollout = [QuotaWindow("codex", 10_080, 47, 10_000, 90)]
        source._quota_windows = [account]
        source._quota_updated_at = 100

        account_windows, account_updated_at = source.quota_windows(now=120)
        windows, origin = MonitorService._select_quota_windows(
            rollout,
            account_windows,
            account_updated_at,
        )

        self.assertEqual(origin, "codex-account-rate-limits")
        self.assertEqual(windows, [account])


class UsageStreakServiceTests(unittest.TestCase):
    def test_counter_reset_after_report_suspends_old_calibration(self):
        now = 1_700_000_000
        short = QuotaWindow("codex", 300, 80, now + 900, now)
        task = TurnDisplayTests._task("a", "running", now - 100, None, 500)
        collector = Mock()
        collector.task_period_token_usage.return_value = {"a": 100}
        service = self._service(collector)
        collector.task_period_token_data.return_value = {"tokens": {"a": 100}, "last_counter_reset_at": now + 1}
        collector.task_period_token_data.side_effect = None
        service.store.token_budget_estimate = Mock(return_value={"tokens_per_percent": 1000})
        result = service._token_budget(MonitorSnapshot(now + 5, "test", "ok", [task], [short]), [short], {}, {}, "test")
        self.assertEqual(result["state"], "calibrating")
        self.assertIsNone(result["available_tokens"])
        service.store.token_budget_estimate.assert_not_called()

    def test_counter_reset_separates_observation_scopes(self):
        now = 1_700_000_000
        short = QuotaWindow("codex", 300, 80, now + 900, now)
        task = TurnDisplayTests._task("a", "running", now - 100, None, 500)
        collector = Mock()
        collector.task_period_token_usage.return_value = {"a": 100}
        service = self._service(collector)
        service.store.record_budget_observation = Mock()
        service._token_budget(MonitorSnapshot(now, "test", "ok", [task], [short]), [short], {}, {}, "test")
        before = service.store.record_budget_observation.call_args.args[2]
        collector.task_period_token_data.side_effect = None
        collector.task_period_token_data.return_value = {"tokens": {"a": 100}, "last_counter_reset_at": now + 1}
        latest = QuotaWindow("codex", 300, 81, now + 900, now + 10)
        service._token_budget(MonitorSnapshot(now + 10, "test", "ok", [task], [latest]), [latest], {}, {}, "test")
        after = service.store.record_budget_observation.call_args.args[2]
        self.assertNotEqual(before, after)

    def test_real_calibration_survives_restart_and_deducts_unreported_usage(self) -> None:
        now = 1_700_000_000
        resets_at = now + 900
        task = TurnDisplayTests._task("a", "running", now - 100, None, 500)
        collector = Mock()
        collector.task_period_token_usage.side_effect = lambda _tasks, _start, end: {
            "a": 5000 if end <= now else 20_000 if end <= now + 60 else 25_000
        }
        service = self._service(collector)
        first = QuotaWindow("codex", 300, 75, resets_at, now)
        initial = service._token_budget(MonitorSnapshot(now, "test", "ok", [task], [first]), [first], {}, {"a": 10_000}, "test")
        self.assertEqual(initial["state"], "calibrating")
        latest = QuotaWindow("codex", 300, 80, resets_at, now + 60)
        raw = MonitorSnapshot(now + 65, "test", "ok", [task], [latest])
        calibrated = service._token_budget(raw, [latest], {}, {"a": 10_000}, "test")
        self.assertEqual(calibrated["available_tokens"], 25_000)
        self.assertEqual(calibrated["unreported_tokens"], 5000)
        self.assertEqual(calibrated["allocations"]["a"]["window_used_tokens"], 25_000)
        restarted = MonitorService(service.store.path.parent, title_source=service.title_source)
        restarted.collector = collector
        resumed = restarted._token_budget(raw, [latest], {}, {"a": 10_000}, "test")
        self.assertEqual(resumed["available_tokens"], 25_000)

    def test_stale_weekly_constraint_does_not_create_an_optimistic_short_budget(self) -> None:
        now = 1_700_000_000
        short = QuotaWindow("codex", 300, 10, now + 900, now)
        weekly = QuotaWindow("codex", 10080, 100, now + 9000, now - 120)
        task = TurnDisplayTests._task("a", "running", now - 100, None, 500)
        service = self._service(Mock())
        service.collector.task_period_token_usage.return_value = {"a": 500}
        service.store.token_budget_estimate = Mock(return_value={"tokens_per_percent": 1000})
        result = service._token_budget(MonitorSnapshot(now, "test", "ok", [task], [short, weekly]), [short], {}, {}, "test")
        self.assertEqual(result["state"], "awaiting_quota")
        self.assertIsNone(result["available_tokens"])

    def test_token_budget_is_shared_by_task_api_and_popup_rows(self) -> None:
        now = 1_700_000_000
        short = QuotaWindow("codex", 300, 80, now + 900, now)
        task = TurnDisplayTests._task("a", "running", now - 100, None, 500)
        collector = Mock()
        collector.collect.return_value = MonitorSnapshot(now, "test", "ok", [task], [short])
        collector.daily_token_usage.return_value = 1000
        collector.usage_streak.return_value = {"days": 1, "tokens": 1000}
        collector.task_period_token_usage.return_value = {"a": 500}
        service = self._service(collector)
        service.store.record_budget_observation(QuotaWindow("codex", 300, 75, short.resets_at, now - 60), 0, "seed", "test")
        service.store.token_budget_estimate = Mock(return_value={"tokens_per_percent": 1000})
        service.store.task_burn_rates = Mock(return_value={"a": 1000})
        snapshot = service.snapshot()
        self.assertEqual(snapshot["health"], "ok")
        self.assertIn("token_budget", snapshot["budget_plan"])
        token = snapshot["tasks"][0]["budget"]["token"]
        self.assertEqual(token["window_used_tokens"], 500)
        self.assertEqual(token["remaining_tokens"], 10000)
        self.assertEqual(snapshot["turn_display"]["tasks"][0]["token_budget"], token)

    def _service(self, collector: Mock) -> MonitorService:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        title_source = Mock()
        title_source.titles.return_value = {}
        title_source.quota_windows.return_value = ([], None)
        title_source.status.return_value = {"source": "test"}
        service = MonitorService(Path(directory.name), title_source=title_source)
        service.collector = collector
        collector.task_period_token_data.side_effect = lambda tasks, start, end=None: {
            "tokens": collector.task_period_token_usage(tasks, start, end),
            "last_counter_reset_at": 0,
        }
        return service

    def test_service_snapshot_exposes_usage_streak(self) -> None:
        collector = Mock()
        collector.collect.return_value = MonitorSnapshot(
            generated_at=1_750_000_000,
            source="test",
            health="ok",
            tasks=[],
            quota_windows=[],
        )
        collector.daily_token_usage.return_value = 0
        collector.usage_streak.return_value = {
            "days": 2,
            "tokens": 456_789,
            "started_at": 1_700_000_000,
            "current_day_tokens": 123_456,
            "source": "rollout-calendar-delta",
        }
        service = self._service(collector)

        service._refresh()

        self.assertEqual(service.snapshot()["usage_streak"]["days"], 2)
        self.assertEqual(service.snapshot()["usage_streak"]["tokens"], 456_789)
        collector.usage_streak.assert_called_once_with([], 1_750_000_000)

    def test_service_error_snapshot_has_zero_usage_streak(self) -> None:
        collector = Mock()
        collector.collect.side_effect = RuntimeError("collector unavailable")
        service = self._service(collector)

        service._refresh()

        self.assertEqual(service.snapshot()["budget_plan"]["token_budget"]["state"], "unavailable")
        self.assertIsNone(service.snapshot()["budget_plan"]["token_budget"]["available_tokens"])

        self.assertEqual(
            service.snapshot()["usage_streak"],
            {
                "days": 0,
                "tokens": 0,
                "started_at": None,
                "current_day_tokens": 0,
                "source": "unavailable",
            },
        )


if __name__ == "__main__":
    unittest.main()
