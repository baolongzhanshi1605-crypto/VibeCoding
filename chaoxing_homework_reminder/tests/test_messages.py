from datetime import datetime, timedelta, timezone
import unittest

from cx_reminder.models import Assignment, ReminderDecision
from cx_reminder.notifiers.messages import format_reminder_message
from cx_reminder.policy import ReminderTier


class MessagesTest(unittest.TestCase):
    def test_formats_message_with_course_title_due_and_tier(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        assignment = Assignment(
            assignment_id="a1",
            course="English",
            title="Unit 5",
            due_at=now + timedelta(hours=2),
            submitted=False,
        )
        decision = ReminderDecision(assignment, ReminderTier.STRONG, "due within 6 hours")

        message = format_reminder_message(decision, now)

        self.assertIn("English", message)
        self.assertIn("Unit 5", message)
        self.assertIn("STRONG", message)
        self.assertIn("2小时", message)


if __name__ == "__main__":
    unittest.main()
