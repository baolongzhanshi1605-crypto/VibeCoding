import unittest
from pathlib import Path


class UsageStreakDashboardTests(unittest.TestCase):
    def test_dashboard_contains_usage_streak_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        script = (root / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="usage-streak-days"', html)
        self.assertIn('id="usage-streak-total"', html)
        self.assertIn('id="usage-streak-today"', html)
        self.assertIn("function updateUsageStreak()", script)
        self.assertIn("updateUsageStreak();", script)
        self.assertNotIn('updateQuotaCard("short", "short")', script)


if __name__ == "__main__":
    unittest.main()
