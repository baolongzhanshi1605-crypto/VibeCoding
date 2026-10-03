import unittest
import subprocess
from unittest.mock import patch

from codex_link import CodexExitGuard, LifecycleController, codex_desktop_pids, ensure_widget, is_codex_desktop_tree


class CodexLinkTests(unittest.TestCase):
    @patch("codex_link.WIDGET_DISMISSED_PATH")
    @patch("codex_link.WIDGET_PID_PATH")
    @patch("codex_link.subprocess.Popen")
    @patch("codex_link.read_pid", return_value=None)
    def test_legacy_close_marker_does_not_block_popup_recovery(self, read, spawn, pid_path, dismissed) -> None:
        dismissed.exists.return_value = True
        spawn.return_value.pid = 4321
        ensure_widget()
        spawn.assert_called_once()
        pid_path.write_text.assert_called_once_with("4321", encoding="ascii")

    def test_detects_codex_app_server_parented_by_desktop(self) -> None:
        entries = [
            ("chatgpt.exe", 100, 10),
            ("codex.exe", 200, 100),
            ("codex-code-mode-host.exe", 300, 200),
        ]
        self.assertTrue(is_codex_desktop_tree(entries))
        self.assertEqual(codex_desktop_pids(entries), {100})

    def test_ignores_standalone_codex_cli(self) -> None:
        entries = [
            ("powershell.exe", 100, 10),
            ("codex.exe", 200, 100),
        ]
        self.assertFalse(is_codex_desktop_tree(entries))

    def test_requires_codex_child(self) -> None:
        self.assertFalse(is_codex_desktop_tree([("chatgpt.exe", 100, 10)]))

    def test_exit_guard_ignores_a_brief_process_gap(self) -> None:
        guard = CodexExitGuard()
        self.assertFalse(guard.should_exit(False, 10))
        self.assertFalse(guard.should_exit(False, 14))
        self.assertFalse(guard.should_exit(True, 15))
        self.assertFalse(guard.should_exit(False, 30))
        self.assertTrue(guard.should_exit(False, 35))

    @patch("codex_link.logging.exception")
    @patch("codex_link.stop_monitoring")
    @patch("codex_link.ensure_widget")
    @patch("codex_link.dashboard_running", return_value=True)
    @patch("codex_link.ensure_dashboard")
    @patch("codex_link.codex_desktop_running", return_value=True)
    @patch("codex_link.time.monotonic")
    def test_startup_timeout_is_retried_and_later_exit_is_cleaned_up(
        self, clock, active, start, healthy, widget, stop, log_error
    ) -> None:
        controller = LifecycleController()
        start.side_effect = [subprocess.TimeoutExpired("start_dashboard", 60), None]
        clock.return_value = 10
        controller.tick()
        self.assertEqual(start.call_count, 1)
        widget.assert_not_called()
        log_error.assert_called_once()
        clock.return_value = 11
        controller.tick()
        self.assertEqual(start.call_count, 1)
        clock.return_value = 15
        controller.tick()
        widget.assert_called_once()
        active.return_value = False
        clock.return_value = 20
        controller.tick()
        stop.assert_not_called()
        clock.return_value = 25
        controller.tick()
        stop.assert_called_once()
        clock.return_value = 30
        controller.tick()
        stop.assert_called_once()

    @patch("codex_link.logging.exception")
    @patch("codex_link.stop_monitoring")
    @patch("codex_link.codex_desktop_running", return_value=False)
    @patch("codex_link.time.monotonic")
    def test_failed_cleanup_is_retried(self, clock, active, stop, log_error) -> None:
        controller = LifecycleController()
        stop.side_effect = [OSError("temporary stop failure"), None]
        for now in (10, 15, 20):
            clock.return_value = now
            controller.tick()
        self.assertEqual(stop.call_count, 2)

    @patch("codex_link.stop_monitoring")
    @patch("codex_link.ensure_widget")
    @patch("codex_link.dashboard_running", return_value=True)
    @patch("codex_link.ensure_dashboard")
    @patch("codex_link.codex_desktop_running")
    @patch("codex_link.time.monotonic")
    def test_reopening_codex_recovers_monitoring_on_each_cycle(
        self, clock, active, start, healthy, widget, stop
    ) -> None:
        controller = LifecycleController()
        for cycle in range(3):
            now = 10 + cycle * 20
            clock.return_value = now
            active.return_value = True
            controller.tick()
            self.assertEqual(widget.call_count, cycle + 1)
            active.return_value = False
            clock.return_value = now + 1
            controller.tick()
            self.assertEqual(stop.call_count, cycle)
            clock.return_value = now + 6
            controller.tick()
            self.assertEqual(stop.call_count, cycle + 1)
        self.assertEqual(start.call_count, 3)


if __name__ == "__main__":
    unittest.main()
