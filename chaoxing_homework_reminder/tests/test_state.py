from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from cx_reminder.models import Assignment, ReminderDecision
from cx_reminder.policy import ReminderTier
from cx_reminder.state import ReminderState


class ReminderStateTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        self.assignment = Assignment(
            assignment_id="a1",
            course="English",
            title="Unit 5",
            due_at=self.now + timedelta(hours=2),
            submitted=False,
        )

    def decision(self, tier):
        return ReminderDecision(self.assignment, tier, "reason")

    def test_preview_reminder_is_limited_to_once_per_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = ReminderState(Path(temp_dir) / "state.json")
            first = state.should_send(self.decision(ReminderTier.PREVIEW), self.now, "login")
            state.mark_sent(self.decision(ReminderTier.PREVIEW), self.now)
            second = state.should_send(
                self.decision(ReminderTier.PREVIEW),
                self.now + timedelta(hours=2),
                "unlock",
            )

        self.assertTrue(first)
        self.assertFalse(second)

    def test_urgent_reminder_repeats_after_fifteen_minutes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = ReminderState(Path(temp_dir) / "state.json")
            decision = self.decision(ReminderTier.URGENT)
            state.mark_sent(decision, self.now)

            too_soon = state.should_send(decision, self.now + timedelta(minutes=10), "timer")
            after_interval = state.should_send(
                decision,
                self.now + timedelta(minutes=16),
                "timer",
            )

        self.assertFalse(too_soon)
        self.assertTrue(after_interval)

    def test_none_decision_never_sends(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = ReminderState(Path(temp_dir) / "state.json")
            self.assertFalse(
                state.should_send(self.decision(ReminderTier.NONE), self.now, "login")
            )


if __name__ == "__main__":
    unittest.main()
