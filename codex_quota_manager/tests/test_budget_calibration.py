import tempfile
import unittest
from pathlib import Path

from codex_monitor.models import QuotaWindow
from codex_monitor.store import SnapshotStore


class BudgetCalibrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = SnapshotStore(Path(temporary.name) / "manager.sqlite")

    def record(self, at, used, tokens, reset=20000, scope="same"):
        method = getattr(self.store, "record_budget_observation", None)
        self.assertTrue(callable(method), "calibration needs paired quota and local Token observations")
        window = QuotaWindow("codex", 300, used, reset, at)
        method(window, tokens, scope, "test")
        return window

    def estimate(self, window, scope="same"):
        return self.store.token_budget_estimate(window, scope, "test")

    def test_estimate_uses_token_delta_not_historical_task_total(self):
        self.record(3000, 10, 1_000_000)
        window = self.record(3060, 15, 1_005_000)
        result = self.estimate(window)
        self.assertEqual(result["tokens_per_percent"], 1000)
        self.assertEqual(result["consumed_tokens"], 5000)

    def test_reset_or_scope_change_cannot_reuse_old_calibration(self):
        self.record(3000, 10, 1000)
        self.record(3060, 15, 6000)
        window = self.record(3120, 0, 0, reset=22000)
        self.assertIsNone(self.estimate(window)["tokens_per_percent"])
        window = self.record(3180, 20, 500_000, scope="changed")
        self.assertIsNone(self.estimate(window, "changed")["tokens_per_percent"])

    def test_quota_decrease_invalidates_previous_segment(self):
        self.record(3000, 10, 1000)
        self.record(3060, 15, 6000)
        window = self.record(3120, 1, 7000)
        self.assertIsNone(self.estimate(window)["tokens_per_percent"])

    def test_zero_local_usage_and_small_quota_changes_do_not_calibrate(self):
        self.record(3000, 10, 1000)
        window = self.record(3060, 11, 2000)
        self.assertIsNone(self.estimate(window)["tokens_per_percent"])
        window = self.record(3120, 15, 1000)
        self.assertIsNone(self.estimate(window)["tokens_per_percent"])


if __name__ == "__main__":
    unittest.main()
