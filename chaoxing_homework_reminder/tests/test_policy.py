from datetime import datetime, timedelta, timezone
import unittest

from cx_reminder.models import Assignment
from cx_reminder.policy import ReminderPolicy, ReminderTier


class ReminderPolicyTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        self.policy = ReminderPolicy(lookahead_hours=36)

    def assignment(self, hours_until_due, submitted=False):
        return Assignment(
            assignment_id="a1",
            course="English",
            title="Unit 5",
            due_at=self.now + timedelta(hours=hours_until_due),
            submitted=submitted,
        )

    def test_submitted_assignment_does_not_notify(self):
        decision = self.policy.decide(self.assignment(1, submitted=True), self.now)
        self.assertEqual(decision.tier, ReminderTier.NONE)

    def test_assignment_due_within_one_hour_is_urgent(self):
        decision = self.policy.decide(self.assignment(0.75), self.now)
        self.assertEqual(decision.tier, ReminderTier.URGENT)

    def test_assignment_due_within_six_hours_is_strong(self):
        decision = self.policy.decide(self.assignment(4), self.now)
        self.assertEqual(decision.tier, ReminderTier.STRONG)

    def test_assignment_due_within_lookahead_is_preview(self):
        decision = self.policy.decide(self.assignment(20), self.now)
        self.assertEqual(decision.tier, ReminderTier.PREVIEW)

    def test_assignment_beyond_lookahead_does_not_notify(self):
        decision = self.policy.decide(self.assignment(40), self.now)
        self.assertEqual(decision.tier, ReminderTier.NONE)

    def test_overdue_assignment_notifies_once_as_overdue(self):
        decision = self.policy.decide(self.assignment(-2), self.now)
        self.assertEqual(decision.tier, ReminderTier.OVERDUE)


if __name__ == "__main__":
    unittest.main()
