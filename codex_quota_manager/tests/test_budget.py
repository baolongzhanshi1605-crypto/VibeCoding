import time
import unittest

from codex_monitor.budget import BudgetPlanner
from codex_monitor.models import QuotaWindow, TaskSnapshot, TokenUsage


def task(task_id: str, status: str = "running") -> TaskSnapshot:
    return TaskSnapshot(
        id=task_id,
        title=task_id,
        cwd="F:\\Codex_project",
        source="vscode",
        model="gpt-test",
        reasoning_effort=None,
        status=status,
        updated_at=int(time.time()),
        tokens=TokenUsage(total_tokens=1000),
        rollout_path="sample.jsonl",
    )


class BudgetPlannerTests(unittest.TestCase):
    def test_uses_tighter_of_short_and_weekly_allowance(self) -> None:
        now = 1_700_000_000
        windows = [
            QuotaWindow("codex", 300, 20, now + 3600, now),
            QuotaWindow("codex", 10080, 40, now + 50 * 3600, now),
        ]
        result = BudgetPlanner().plan([task("a"), task("b")], windows, {}, {}, now=now)

        # Weekly remaining after reserve is 45 points across ten five-hour slots.
        self.assertEqual(result["source"], "short_and_weekly")
        self.assertEqual(result["available_percent"], 4.5)
        self.assertEqual(result["allocations"]["a"]["cap_percent"], 2.25)
        self.assertEqual(result["allocations"]["b"]["cap_percent"], 2.25)

    def test_priority_increases_share_without_exceeding_cap(self) -> None:
        now = 1_700_000_000
        windows = [QuotaWindow("codex", 300, 10, now + 3600, now)]
        preferences = {"a": {"priority": 5}, "b": {"priority": 1}}
        result = BudgetPlanner().plan([task("a"), task("b")], windows, preferences, {}, now=now)

        self.assertEqual(result["allocations"]["a"]["cap_percent"], 40.0)
        self.assertGreater(result["allocations"]["a"]["cap_percent"], result["allocations"]["b"]["cap_percent"])

    def test_completed_tasks_receive_no_budget(self) -> None:
        now = 1_700_000_000
        windows = [QuotaWindow("codex", 300, 10, now + 3600, now)]
        result = BudgetPlanner().plan([task("done", "completed")], windows, {}, {}, now=now)
        self.assertEqual(result["allocations"], {})

    def test_manual_budget_overrides_automatic_and_preserves_total_pool(self) -> None:
        now = 1_700_000_000
        windows = [QuotaWindow("codex", 300, 80, now + 3600, now)]
        preferences = {"a": {"priority": 3, "manual_cap_percent": 8}}

        result = BudgetPlanner().plan([task("a"), task("b")], windows, preferences, {}, now=now)

        self.assertEqual(result["available_percent"], 10.0)
        self.assertEqual(result["allocations"]["a"]["automatic_percent"], 5.0)
        self.assertEqual(result["allocations"]["a"]["cap_percent"], 8.0)
        self.assertEqual(result["allocations"]["b"]["cap_percent"], 2.0)
        self.assertEqual(result["allocations"]["a"]["mode"], "manual")

    def test_manual_budgets_are_scaled_when_they_exceed_available_pool(self) -> None:
        now = 1_700_000_000
        windows = [QuotaWindow("codex", 300, 80, now + 3600, now)]
        preferences = {
            "a": {"priority": 3, "manual_cap_percent": 8},
            "b": {"priority": 3, "manual_cap_percent": 8},
        }

        result = BudgetPlanner().plan([task("a"), task("b")], windows, preferences, {}, now=now)

        self.assertEqual(result["allocations"]["a"]["cap_percent"], 5.0)
        self.assertEqual(result["allocations"]["b"]["cap_percent"], 5.0)
        self.assertEqual(result["allocations"]["a"]["mode"], "manual_adjusted")


if __name__ == "__main__":
    unittest.main()
