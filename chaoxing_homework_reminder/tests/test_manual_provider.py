from pathlib import Path
import tempfile
import unittest

from cx_reminder.providers.manual_json import ManualJsonProvider


class ManualJsonProviderTest(unittest.TestCase):
    def test_loads_assignments_from_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "assignments.json"
            path.write_text(
                """
[
  {
    "assignment_id": "a1",
    "course": "English",
    "title": "Unit 5",
    "due_at": "2026-06-10T22:00:00+08:00",
    "submitted": false
  }
]
""".strip(),
                encoding="utf-8",
            )

            assignments = ManualJsonProvider(path).fetch_assignments()

        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].course, "English")
        self.assertFalse(assignments[0].submitted)


if __name__ == "__main__":
    unittest.main()
