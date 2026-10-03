import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from codex_monitor.collector import CodexCollector, ParsedRollout, _select_active_codex_home
from codex_monitor.models import TaskSnapshot, TokenUsage


class CollectorTests(unittest.TestCase):
    def test_per_task_window_usage_excludes_history_and_honors_end_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            epoch = 1_700_000_000
            path = self._write_token_counts(directory, "window.jsonl", [(epoch + 90, 10000), (epoch + 100, 10500), (epoch + 150, 12000), (epoch + 210, 13000)])
            collector = CodexCollector(codex_home=Path(directory))
            method = getattr(collector, "task_period_token_usage", None)
            self.assertTrue(callable(method), "per-task window usage is required")
            tasks = [self._task("a", path, 13000)]
            self.assertEqual(method(tasks, epoch + 100, epoch + 200), {"a": 2000})
            self.assertEqual(method(tasks, epoch + 200), {"a": 1000})

    def test_window_usage_counts_new_counter_segment_and_exposes_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            epoch = 1_700_000_000
            path = self._write_token_counts(directory, "reset.jsonl", [(epoch + 90, 1000), (epoch + 100, 1500), (epoch + 150, 100), (epoch + 200, 300)])
            collector = CodexCollector(codex_home=Path(directory))
            tasks = [self._task("a", path, 300)]
            self.assertEqual(collector.task_period_token_usage(tasks, epoch + 100), {"a": 800})
            data = collector.task_period_token_data(tasks, epoch + 100)
            self.assertEqual(data["last_counter_reset_at"], epoch + 150)
            self.assertEqual(data["tokens"], {"a": 800})

    @staticmethod
    def _task(task_id: str, path: Path, tokens: int) -> TaskSnapshot:
        return TaskSnapshot(
            id=task_id,
            title=task_id,
            cwd="C:/repo",
            source="desktop",
            model=None,
            reasoning_effort=None,
            status="running",
            updated_at=2_100,
            tokens=TokenUsage(total_tokens=tokens),
            rollout_path=str(path),
        )

    @staticmethod
    def _local_epoch(year: int, month: int, day: int, hour: int) -> int:
        return int(datetime(year, month, day, hour).timestamp())

    @staticmethod
    def _token_record(epoch: int, total_tokens: int) -> dict[str, object]:
        return {
            "timestamp": datetime.fromtimestamp(epoch).astimezone().isoformat(),
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"total_tokens": total_tokens}},
            },
        }

    @classmethod
    def _write_token_counts(
        cls,
        directory: str,
        name: str,
        samples: list[tuple[int, int]],
    ) -> Path:
        path = Path(directory) / name
        records = [cls._token_record(epoch, total_tokens) for epoch, total_tokens in samples]
        path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
        return path

    def test_rollout_parser_reads_tokens_windows_and_running_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            records = [
                {
                    "timestamp": "2026-07-13T05:00:00Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-test", "reasoning_effort": "high"},
                },
                {
                    "timestamp": "2026-07-13T05:00:01Z",
                    "type": "event_msg",
                    "payload": {"type": "task_started"},
                },
                {
                    "timestamp": "2026-07-13T05:00:02Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 900,
                                "cached_input_tokens": 600,
                                "output_tokens": 100,
                                "reasoning_output_tokens": 25,
                                "total_tokens": 1000,
                            }
                        },
                        "rate_limits": {
                            "limit_id": "codex",
                            "primary": {"used_percent": 12, "window_minutes": 300, "resets_at": 2000000000},
                            "secondary": {"used_percent": 28, "window_minutes": 10080, "resets_at": 2000500000},
                        },
                    },
                },
            ]
            path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

            parsed = CodexCollector()._parse_rollout(path)

            self.assertEqual(parsed.status, "running")
            self.assertEqual(parsed.model, "gpt-test")
            self.assertEqual(parsed.tokens.total_tokens, 1000)
            self.assertEqual(parsed.turn_tokens, 1000)
            self.assertEqual(parsed.turn_started_at, 1783918801)
            self.assertEqual([window.kind for window in parsed.quota_windows], ["short", "weekly"])

    def test_active_codex_home_uses_most_recent_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old_home = Path(directory) / "old"
            active_home = Path(directory) / "active"
            old_home.mkdir()
            active_home.mkdir()
            old_state = old_home / "state_5.sqlite"
            active_state = active_home / "state_5.sqlite"
            old_state.write_bytes(b"")
            active_state.write_bytes(b"")
            old_state.touch()
            active_state.touch()
            old_state_time = old_state.stat().st_mtime_ns
            active_state_time = old_state_time + 1_000_000_000
            os.utime(active_state, ns=(active_state_time, active_state_time))

            selected = _select_active_codex_home([old_home, active_home])

            self.assertEqual(selected, active_home)

    def test_explicit_codex_home_is_not_auto_switched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixed_home = Path(directory) / "fixed"
            fixed_home.mkdir()
            collector = CodexCollector(codex_home=fixed_home)

            collector._refresh_codex_home()

            self.assertEqual(collector.codex_home, fixed_home)

    def test_latest_turn_tokens_do_not_include_previous_turns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            records = [
                {
                    "timestamp": "2026-07-13T05:00:00Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {"total_tokens": 100},
                            "last_token_usage": {"total_tokens": 100},
                        },
                    },
                },
                {
                    "timestamp": "2026-07-13T05:01:00Z",
                    "type": "event_msg",
                    "payload": {"type": "task_complete"},
                },
                {
                    "timestamp": "2026-07-13T05:02:00Z",
                    "type": "event_msg",
                    "payload": {"type": "task_started"},
                },
                {
                    "timestamp": "2026-07-13T05:02:10Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {"total_tokens": 160},
                            "last_token_usage": {"total_tokens": 60},
                        },
                    },
                },
                {
                    "timestamp": "2026-07-13T05:02:20Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {"total_tokens": 220},
                            "last_token_usage": {"total_tokens": 60},
                        },
                    },
                },
                {
                    "timestamp": "2026-07-13T05:02:30Z",
                    "type": "event_msg",
                    "payload": {"type": "task_complete"},
                },
            ]
            path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

            parsed = CodexCollector()._parse_rollout(path)

            self.assertEqual(parsed.status, "completed")
            self.assertEqual(parsed.tokens.total_tokens, 220)
            self.assertEqual(parsed.turn_tokens, 120)
            self.assertEqual(parsed.turn_started_at, 1783918920)
            self.assertEqual(parsed.turn_finished_at, 1783918950)

    def test_waiting_permission_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            records = [
                {"timestamp": "2026-07-13T05:00:01Z", "type": "event_msg", "payload": {"type": "task_started"}},
                {
                    "timestamp": "2026-07-13T05:00:02Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "shell_command",
                        "arguments": "{\"sandbox_permissions\":\"require_escalated\"}",
                    },
                },
            ]
            path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

            parsed = CodexCollector()._parse_rollout(path)

            self.assertEqual(parsed.status, "waiting")
            self.assertEqual(parsed.pending_tool, "shell_command")

    def test_stale_state_is_handled_by_collector_snapshot_layer(self) -> None:
        parsed = ParsedRollout(status="running", last_event_at=100)
        self.assertEqual(CodexCollector._normalized_status(parsed, 401), "idle")
        parsed.pending_tool = "shell_command"
        self.assertEqual(CodexCollector._normalized_status(parsed, 401), "running")
        parsed.status = "paused"
        parsed.pending_tool = None
        self.assertEqual(CodexCollector._normalized_status(parsed, 401), "idle")

    def test_daily_usage_uses_last_token_total_before_day_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old_task_path = Path(directory) / "old.jsonl"
            new_task_path = Path(directory) / "new.jsonl"
            old_task_path.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in [
                        {
                            "timestamp": "1970-01-01T00:25:00Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "token_count",
                                "info": {"total_token_usage": {"total_tokens": 100}},
                            },
                        },
                        {
                            "timestamp": "1970-01-01T00:35:00Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "token_count",
                                "info": {"total_token_usage": {"total_tokens": 300}},
                            },
                        },
                    ]
                ),
                encoding="utf-8",
            )
            new_task_path.write_text(
                json.dumps(
                    {
                        "timestamp": "1970-01-01T00:35:00Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {"total_token_usage": {"total_tokens": 500}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            collector = CodexCollector()
            tasks = [
                self._task("old", old_task_path, 300),
                self._task("new", new_task_path, 500),
            ]

            self.assertEqual(collector.daily_token_usage(tasks, day_start_epoch=2_000), 700)

    def test_period_usage_recalculates_when_window_start_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weekly.jsonl"
            records = [
                {
                    "timestamp": "1970-01-01T00:16:40Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"total_token_usage": {"total_tokens": 100}},
                    },
                },
                {
                    "timestamp": "1970-01-01T00:33:20Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"total_token_usage": {"total_tokens": 300}},
                    },
                },
                {
                    "timestamp": "1970-01-01T00:50:00Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"total_token_usage": {"total_tokens": 600}},
                    },
                },
            ]
            path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            collector = CodexCollector()
            task = self._task("weekly", path, 600)

            self.assertEqual(collector.period_token_usage([task], period_start_epoch=1_500), 500)
            self.assertEqual(collector.period_token_usage([task], period_start_epoch=2_500), 300)

    def test_usage_streak_breaks_after_zero_use_calendar_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            collector = CodexCollector()
            path = self._write_token_counts(
                directory,
                "gap.jsonl",
                [
                    (self._local_epoch(2026, 7, 26, 12), 100),
                    (self._local_epoch(2026, 7, 27, 12), 300),
                    (self._local_epoch(2026, 7, 29, 12), 700),
                ],
            )

            result = collector.usage_streak(
                [self._task("gap", path, 700)],
                self._local_epoch(2026, 7, 29, 18),
            )

            self.assertEqual(result["days"], 1)
            self.assertEqual(result["tokens"], 400)
            self.assertEqual(result["current_day_tokens"], 400)

    def test_usage_streak_aggregates_multiple_rollouts_for_one_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            collector = CodexCollector()
            first = self._write_token_counts(
                directory,
                "first.jsonl",
                [(self._local_epoch(2026, 7, 29, 9), 300)],
            )
            second = self._write_token_counts(
                directory,
                "second.jsonl",
                [(self._local_epoch(2026, 7, 29, 11), 500)],
            )

            result = collector.usage_streak(
                [self._task("first", first, 300), self._task("second", second, 500)],
                self._local_epoch(2026, 7, 29, 18),
            )

            self.assertEqual(result["days"], 1)
            self.assertEqual(result["tokens"], 800)
            self.assertEqual(result["current_day_tokens"], 800)

    def test_usage_streak_is_zero_before_today_has_token_activity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            collector = CodexCollector()
            path = self._write_token_counts(
                directory,
                "yesterday.jsonl",
                [(self._local_epoch(2026, 7, 28, 18), 600)],
            )

            result = collector.usage_streak(
                [self._task("yesterday", path, 600)],
                self._local_epoch(2026, 7, 29, 18),
            )

            self.assertEqual(
                result,
                {
                    "days": 0,
                    "tokens": 0,
                    "started_at": None,
                    "current_day_tokens": 0,
                    "source": "rollout-calendar-delta",
                },
            )

    def test_usage_streak_counts_new_task_first_token_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            collector = CodexCollector()
            path = self._write_token_counts(
                directory,
                "new.jsonl",
                [(self._local_epoch(2026, 7, 29, 10), 900)],
            )

            result = collector.usage_streak(
                [self._task("new", path, 900)],
                self._local_epoch(2026, 7, 29, 18),
            )

            self.assertEqual(result["days"], 1)
            self.assertEqual(result["tokens"], 900)


if __name__ == "__main__":
    unittest.main()
