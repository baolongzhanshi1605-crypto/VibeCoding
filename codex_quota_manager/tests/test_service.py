import unittest

from codex_monitor.models import TaskSnapshot, TokenUsage
from codex_monitor.service import MonitorService


class TurnDisplayTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
