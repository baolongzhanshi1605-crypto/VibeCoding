import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from codex_monitor.store import SnapshotStore


class SnapshotStoreTests(unittest.TestCase):
    def test_preferences_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / "manager.sqlite")
            stored = store.update_preference("task-1", 5, 12.5, True, "额度监控")
            loaded = store.preferences()["task-1"]

            self.assertEqual(stored["priority"], 5)
            self.assertEqual(loaded["manual_cap_percent"], 12.5)
            self.assertTrue(loaded["managed"])
            self.assertEqual(loaded["display_name"], "额度监控")

    def test_rejects_invalid_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / "manager.sqlite")
            with self.assertRaises(ValueError):
                store.update_preference("task-1", 6, None, False)

    def test_rejects_invalid_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / "manager.sqlite")
            with self.assertRaises(ValueError):
                store.update_preference("task-1", 3, None, False, "x" * 33)

    def test_quota_history_is_sampled_per_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / "manager.sqlite")
            now = int(time.time())
            with closing(store._connect()) as connection:
                for offset in range(10):
                    for window in (300, 10080):
                        connection.execute(
                            "insert into quota_snapshots values (?, ?, ?, ?, ?)",
                            (now - 20 + offset, "codex", window, float(offset), now + 1000),
                        )
                connection.commit()

            history = store.quota_history(lookback_seconds=60, max_points_per_window=4)
            short = [item for item in history if item["window_minutes"] == 300]
            weekly = [item for item in history if item["window_minutes"] == 10080]

            self.assertEqual(len(short), 4)
            self.assertEqual(len(weekly), 4)
            self.assertEqual(short[0]["used_percent"], 0.0)
            self.assertEqual(short[-1]["used_percent"], 9.0)



if __name__ == "__main__":
    unittest.main()
