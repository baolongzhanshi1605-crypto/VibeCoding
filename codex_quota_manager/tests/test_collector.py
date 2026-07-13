import json
import tempfile
import unittest
from pathlib import Path

from codex_monitor.collector import CodexCollector, ParsedRollout
from codex_monitor.models import TaskSnapshot, TokenUsage


class CollectorTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
