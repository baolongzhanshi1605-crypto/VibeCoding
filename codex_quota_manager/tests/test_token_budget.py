import unittest

from codex_monitor.budget import BudgetPlanner
from codex_monitor.models import QuotaWindow
from test_budget import task


class TokenBudgetTests(unittest.TestCase):
    now = 1_700_000_000

    def plan(self, tasks=None, windows=None, rates=None, preferences=None, estimates=None):
        planner = BudgetPlanner()
        method = getattr(planner, "plan_tokens", None)
        self.assertTrue(callable(method), "a local Token budget must accompany percentage suggestions")
        short = QuotaWindow("codex", 300, 80, self.now + 900, self.now)
        return method(
            tasks or [task("a"), task("b")], windows if windows is not None else [short],
            preferences or {}, rates or {}, {"a": 3000, "b": 1000},
            estimates if estimates is not None else {"short": {"tokens_per_percent": 1000}},
            window=short, now=self.now,
        )

    def test_parallel_remaining_pool_is_conserved_and_usage_is_separate(self):
        result = self.plan(rates={"a": 1000, "b": 1000})
        self.assertTrue(result["is_estimate"])
        self.assertTrue(result["advisory_only"])
        self.assertEqual(result["available_tokens"], 10_000)
        self.assertEqual(result["allocations"]["a"]["remaining_tokens"], 5000)
        self.assertEqual(result["allocations"]["a"]["window_used_tokens"], 3000)
        self.assertEqual(result["allocations"]["a"]["suggested_total_tokens"], 8000)
        self.assertEqual(result["allocations"]["a"]["exhausts_at"], self.now + 300)

    def test_weekly_constraint_is_compared_in_tokens_not_percentage_points(self):
        short = QuotaWindow("codex", 300, 20, self.now + 900, self.now)
        weekly = QuotaWindow("codex", 10080, 60, self.now + 50 * 3600, self.now)
        result = self.plan(windows=[short, weekly], estimates={
            "short": {"tokens_per_percent": 1000},
            "weekly": {"tokens_per_percent": 10_000},
        })
        self.assertEqual(result["available_tokens"], 25_000)
        self.assertEqual(sum(row["remaining_tokens"] for row in result["allocations"].values()), 25_000)

    def test_manual_targets_share_the_pool_without_overallocation(self):
        result = self.plan(preferences={"a": {"manual_cap_percent": 8}})
        self.assertEqual(result["allocations"]["a"]["remaining_tokens"], 8000)
        self.assertEqual(result["allocations"]["b"]["remaining_tokens"], 2000)
        scaled = self.plan(preferences={"a": {"manual_cap_percent": 8}, "b": {"manual_cap_percent": 8}})
        self.assertEqual(sum(row["remaining_tokens"] for row in scaled["allocations"].values()), 10_000)

    def test_insufficient_samples_never_fabricate_tokens_or_eta(self):
        result = self.plan(estimates={})
        self.assertEqual(result["state"], "calibrating")
        self.assertIsNone(result["available_tokens"])
        self.assertEqual(result["allocations"]["a"]["window_used_tokens"], 3000)
        self.assertIsNone(result["allocations"]["a"]["remaining_tokens"])
        self.assertIsNone(result["allocations"]["a"]["exhausts_at"])

    def test_waiting_and_zero_rate_are_active_without_fabricated_forecasts(self):
        result = self.plan(tasks=[task("a", "waiting"), task("b"), task("done", "completed")], rates={"a": 1000, "b": 0})
        self.assertEqual(result["active_tasks"], 2)
        self.assertNotIn("done", result["allocations"])
        self.assertEqual(result["allocations"]["a"]["forecast"], "waiting")
        self.assertEqual(result["allocations"]["b"]["forecast"], "unknown_rate")

    def test_forecast_does_not_extend_past_reset(self):
        result = self.plan(rates={"a": 1, "b": 1})
        self.assertEqual(result["allocations"]["a"]["forecast"], "after_reset")
        self.assertIsNone(result["allocations"]["a"]["exhausts_at"])

    def test_missing_short_quota_and_safety_reserve_are_distinct(self):
        missing = self.plan(windows=[])
        self.assertEqual(missing["state"], "awaiting_quota")
        exhausted = self.plan(windows=[QuotaWindow("codex", 300, 99, self.now + 900, self.now)], estimates={})
        self.assertEqual(exhausted["available_tokens"], 0)
        self.assertEqual(exhausted["allocations"]["a"]["forecast"], "exhausted")

    def test_priority_and_speed_both_affect_automatic_allocations(self):
        priorities = self.plan(preferences={"a": {"priority": 5}, "b": {"priority": 1}})
        self.assertGreater(priorities["allocations"]["a"]["remaining_tokens"], priorities["allocations"]["b"]["remaining_tokens"])
        rates = self.plan(rates={"a": 4000, "b": 1000})
        self.assertLess(rates["allocations"]["a"]["remaining_tokens"], rates["allocations"]["b"]["remaining_tokens"])

    def test_unreported_tokens_are_deducted_before_splitting(self):
        short = QuotaWindow("codex", 300, 80, self.now + 900, self.now)
        result = BudgetPlanner().plan_tokens(
            [task("a"), task("b")], [short], {}, {}, {"a": 9000, "b": 4000},
            {"short": {"tokens_per_percent": 1000}}, window=short,
            now=self.now, unreported_tokens=6000,
        )
        self.assertEqual(result["available_tokens"], 4000)
        self.assertEqual(sum(row["remaining_tokens"] for row in result["allocations"].values()), 4000)

    def test_invalid_ratios_expired_windows_and_inactive_tasks(self):
        invalid = self.plan(estimates={"short": {"tokens_per_percent": float("inf")}})
        self.assertIsNone(invalid["available_tokens"])
        short = QuotaWindow("codex", 300, 80, self.now, self.now - 60)
        expired = BudgetPlanner().plan_tokens(
            [task("a")], [], {}, {}, {"a": 1000}, {}, window=short, now=self.now,
        )
        self.assertEqual(expired["state"], "awaiting_quota")
        self.assertIsNone(expired["allocations"]["a"]["window_used_tokens"])
        inactive = self.plan(tasks=[task("done", "completed")])
        self.assertEqual(inactive["active_tasks"], 0)
        self.assertEqual(inactive["allocations"], {})

    def test_fractional_calibration_never_overallocates_or_exceeds_task_cap(self):
        result = self.plan(estimates={"short": {"tokens_per_percent": 999.99}})
        self.assertLessEqual(sum(row["remaining_tokens"] for row in result["allocations"].values()), result["available_tokens"])
        cap = self.plan(
            tasks=[task("a")], windows=[QuotaWindow("codex", 300, 0, self.now + 900, self.now)],
            preferences={"a": {"manual_cap_percent": 100}},
        )
        self.assertEqual(cap["allocations"]["a"]["remaining_tokens"], 40_000)


if __name__ == "__main__":
    unittest.main()
