from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from cx_reminder.models import Assignment
from cx_reminder.policy import ReminderPolicy
from cx_reminder.runner import CheckResult, run_check
from cx_reminder.state import ReminderState


class MemoryNotifier:
    def __init__(self):
        self.messages = []

    def send(self, title, content):
        self.messages.append((title, content))
        return True


class StaticProvider:
    def __init__(self, assignments):
        self.assignments = assignments

    def fetch_assignments(self):
        return self.assignments


class RunnerTest(unittest.TestCase):
    def test_run_check_sends_and_records_due_assignment(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        assignment = Assignment(
            assignment_id="a1",
            course="English",
            title="Unit 5",
            due_at=now + timedelta(hours=2),
            submitted=False,
        )
        notifier = MemoryNotifier()

        with tempfile.TemporaryDirectory() as temp_dir:
            state = ReminderState(Path(temp_dir) / "state.json")
            result = run_check(
                provider=StaticProvider([assignment]),
                state=state,
                policy=ReminderPolicy(),
                notifiers=[notifier],
                now=now,
                trigger="login",
            )

        self.assertEqual(result, CheckResult(checked=1, notified=1, skipped=0))
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("English", notifier.messages[0][1])


if __name__ == "__main__":
    unittest.main()
