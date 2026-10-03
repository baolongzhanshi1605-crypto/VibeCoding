import unittest
import queue
import json
import threading
import urllib.request
import os
import ctypes
import tkinter as tk
import subprocess
import sys
import time
from contextlib import ExitStack
from ctypes import wintypes
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from desktop_widget import (
    DASHBOARD_URL,
    CodexActivationTracker,
    TokenWidget,
    USER32,
    apply_native_titlebar_theme,
    bind_titlebar_theme_sync,
    format_task_activity_line,
    format_usage_streak,
    format_exact_tokens,
    native_root_window,
    open_dashboard,
    palette_for,
    singleton_available,
    titlebar_attributes,
)


class DesktopWidgetTextTests(unittest.TestCase):
    def test_active_task_budget_line_uses_window_usage_and_estimate(self) -> None:
        line = format_task_activity_line(1, {
            "name": "并行任务", "status": "running", "cumulative_tokens": 1_000_000,
            "turn_tokens": 100, "token_budget": {"window_used_tokens": 20_000,
                "remaining_tokens": 50_000, "forecast": "exhausts", "seconds_remaining": 300},
        })
        self.assertIn("五小时已用2.0万", line)
        self.assertIn("可用估算5.0万", line)
        self.assertIn("约5分钟耗尽", line)

    def test_active_task_without_calibration_never_displays_fake_budget(self) -> None:
        line = format_task_activity_line(1, {"name": "任务", "status": "running",
            "token_budget": {"window_used_tokens": 100, "remaining_tokens": None, "forecast": "calibrating"}})
        self.assertIn("可用估算校准中", line)
        self.assertNotIn("约0", line)

    def test_codex_click_restores_hidden_popup_but_close_focus_fallback_does_not(self) -> None:
        tracker = CodexActivationTracker()
        tracker.dismiss((90, 999, 0x8000), 10)
        self.assertFalse(tracker.should_reveal((10, 123, 0x8000), {123}, hidden=True, now=10.1))
        self.assertFalse(tracker.should_reveal((10, 123, 0), {123}, hidden=True, now=10.3))
        self.assertTrue(tracker.should_reveal((10, 123, 1), {123}, hidden=True, now=10.5))
        self.assertFalse(tracker.should_reveal((10, 123, 0), {123}, hidden=False, now=10.6))

    def test_codex_activation_raises_visible_popup_and_other_apps_do_not(self) -> None:
        tracker = CodexActivationTracker()
        self.assertFalse(tracker.should_reveal((90, 999, 0), {123}, hidden=False, now=10))
        self.assertTrue(tracker.should_reveal((10, 123, 0), {123}, hidden=False, now=11))
        self.assertFalse(tracker.should_reveal((20, 999, 1), {123}, hidden=True, now=12))

    @patch("desktop_widget.window_activity", return_value=(10, 123, 0))
    def test_close_hides_popup_and_keeps_it_available_for_reactivation(self, activity) -> None:
        widget = TokenWidget.__new__(TokenWidget)
        widget.root = Mock()
        widget.activation_tracker = CodexActivationTracker()
        widget._save_preferences = Mock()
        widget._close_by_user()
        self.assertTrue(widget.hidden_by_user)
        widget.root.withdraw.assert_called_once()
        widget.root.destroy.assert_not_called()
        self.assertEqual(widget.activation_tracker.last_window, 10)

    @patch("desktop_widget.PID_PATH")
    @patch("desktop_widget.pid_running", return_value=True)
    def test_launcher_can_register_popup_pid_before_child_initializes(self, running, pid_path) -> None:
        pid_path.read_text.return_value = str(os.getpid())
        self.assertTrue(singleton_available())
        pid_path.read_text.return_value = str(os.getpid() + 1)
        self.assertFalse(singleton_available())

    def test_daily_detail_keeps_every_digit_when_summary_uses_hundreds_of_millions(self) -> None:
        self.assertEqual(format_exact_tokens(290_123_456), "290,123,456 Token")
        self.assertEqual(format_exact_tokens(None), "0 Token")

    def test_codex_exit_closes_popup_without_marking_it_as_user_dismissed(self) -> None:
        widget = TokenWidget.__new__(TokenWidget)
        widget.root = Mock()
        widget.messages = queue.Queue()
        widget.messages.put(("codex_exit", None))
        widget._close_by_user = Mock()
        widget.status_label = Mock()
        widget._drain_messages()
        widget.root.destroy.assert_called_once()
        widget._close_by_user.assert_not_called()
        widget.root.after.assert_not_called()

    def test_bad_snapshot_does_not_stop_future_refreshes(self) -> None:
        widget = TokenWidget.__new__(TokenWidget)
        widget.root = Mock()
        widget.messages = queue.Queue()
        widget.messages.put(("snapshot", {}))
        widget.status_label = Mock()
        widget.connection_failed = False
        widget._render_snapshot = Mock(side_effect=ValueError("bad snapshot"))
        with patch("desktop_widget.logging.exception"):
            widget._drain_messages()
        widget.root.after.assert_called_once_with(100, widget._drain_messages)

    def test_poll_recovers_after_http_error_and_truncated_response(self) -> None:
        snapshot = {"daily_usage": {"tokens": 290_123_456}}

        class Handler(BaseHTTPRequestHandler):
            requests = 0

            def do_GET(self) -> None:
                Handler.requests += 1
                if Handler.requests == 1:
                    self.send_error(503)
                    return
                body = json.dumps(snapshot).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body) + (100 if Handler.requests == 2 else 0)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        widget = TokenWidget.__new__(TokenWidget)
        widget.stop_event = Mock()
        widget.stop_event.wait.side_effect = [False, False, False, True]
        widget.messages = queue.Queue()
        widget.exit_guard = Mock()
        widget.exit_guard.should_exit.return_value = False
        widget.status_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with patch("desktop_widget.STATUS_URL", f"http://127.0.0.1:{server.server_port}/api/status"), patch(
                "desktop_widget.codex_desktop_running", return_value=True
            ):
                widget._poll()
            self.assertEqual(widget.messages.get_nowait()[0], "error")
            self.assertEqual(widget.messages.get_nowait()[0], "error")
            self.assertEqual(widget.messages.get_nowait(), ("snapshot", snapshot))
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_usage_streak_text_shows_days_and_streak_total(self) -> None:
        self.assertEqual(
            format_usage_streak({"days": 3, "tokens": 1_234_567}),
            ("3 天", "累计 123.5万 Token"),
        )

    def test_zero_usage_streak_is_explicit(self) -> None:
        self.assertEqual(
            format_usage_streak({"days": 0, "tokens": 0}),
            ("0 天", "累计 0 Token"),
        )

    def test_running_task_distinguishes_task_total_from_current_turn(self) -> None:
        line = format_task_activity_line(
            1,
            {
                "name": "新任务",
                "status": "running",
                "cumulative_tokens": 3_231_171,
                "turn_tokens": 880_977,
            },
        )

        self.assertEqual(
            line,
            "1. 新任务｜运行中｜任务累计323.1万｜本轮消耗88.1万 Token",
        )

    def test_completed_task_uses_turn_wording(self) -> None:
        line = format_task_activity_line(
            2,
            {"name": "新任务", "status": "completed", "turn_tokens": 880_977},
        )

        self.assertEqual(
            line,
            "2. 本轮工作：新任务｜已结束｜本轮消耗88.1万 Token",
        )

    @patch("desktop_widget.webbrowser.open")
    def test_dashboard_link_opens_local_display(self, browser_open) -> None:
        open_dashboard()

        browser_open.assert_called_once_with(DASHBOARD_URL, new=2)

    def test_widget_theme_defaults_to_dark_and_supports_light(self) -> None:
        self.assertEqual(palette_for(None)["page"], "#101214")
        self.assertEqual(palette_for("dark")["ink"], "#f2f4f7")
        self.assertEqual(palette_for("light")["page"], "#f7f8fc")

    def test_dark_titlebar_uses_the_popup_palette(self) -> None:
        self.assertEqual(
            titlebar_attributes("dark"),
            ((20, 1), (34, 0x403A34), (35, 0x141210), (36, 0xF7F4F2)),
        )

    def test_titlebar_applies_every_native_attribute(self) -> None:
        calls: list[tuple[int, int, int]] = []

        applied = apply_native_titlebar_theme(
            123,
            "light",
            lambda hwnd, attribute, value: calls.append((hwnd, attribute, value)) or 0,
        )

        self.assertTrue(applied)
        self.assertEqual(calls[0], (123, 20, 0))
        self.assertEqual(
            calls[1:],
            [(123, 34, 0xE8E3DF), (123, 35, 0xFCF8F7), (123, 36, 0x242120)],
        )

    def test_titlebar_applies_to_the_native_root_window(self) -> None:
        calls: list[tuple[int, int, int]] = []

        applied = apply_native_titlebar_theme(
            123,
            "dark",
            lambda hwnd, attribute, value: calls.append((hwnd, attribute, value)) or 0,
            window_resolver=lambda hwnd: 456,
        )

        self.assertTrue(applied)
        self.assertEqual([hwnd for hwnd, _attribute, _value in calls], [456, 456, 456, 456])

    def test_focus_changes_resync_the_native_titlebar_after_repaint(self) -> None:
        class FakeRoot:
            def __init__(self) -> None:
                self.bindings: dict[str, tuple[object, str]] = {}
                self.scheduled: list[tuple[object, ...]] = []

            def bind(self, sequence: str, callback: object, add: str) -> None:
                self.bindings[sequence] = (callback, add)

            def after_idle(self, callback: object) -> None:
                self.scheduled.append(("idle", callback))

            def after(self, milliseconds: int, callback: object) -> None:
                self.scheduled.append(("after", milliseconds, callback))

        root = FakeRoot()

        def refresh() -> None:
            pass

        bind_titlebar_theme_sync(root, refresh)

        for event_name in ("<FocusIn>", "<FocusOut>"):
            callback, add = root.bindings[event_name]
            self.assertEqual(add, "+")
            callback(None)

        self.assertEqual(
            root.scheduled,
            [
                ("idle", refresh),
                ("after", 60, refresh),
                ("idle", refresh),
                ("after", 60, refresh),
            ],
        )


class DesktopWidgetWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.widget: TokenWidget | None = None
        self.addCleanup(self.destroy_widget)
        directory = self.stack.enter_context(TemporaryDirectory())
        self.preferences_path = Path(directory) / "widget.json"
        self.stack.enter_context(patch("desktop_widget.PREFERENCES_PATH", self.preferences_path))
        self.stack.enter_context(patch.object(TokenWidget, "_poll"))
        self.sync_activation = TokenWidget._sync_codex_activation
        self.stack.enter_context(patch.object(TokenWidget, "_sync_codex_activation"))

        def position(widget) -> None:
            widget.root.update_idletasks()
            widget.root.withdraw()
            widget.root.geometry("560x302+40+40")

        self.stack.enter_context(patch.object(TokenWidget, "_position_window", position))
        self.get_style = USER32.GetWindowLongW
        self.get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        self.get_style.restype = wintypes.LONG

    def create_widget(self, preferences: dict) -> TokenWidget:
        self.destroy_widget()
        with patch.object(TokenWidget, "_load_preferences", return_value=preferences):
            widget = TokenWidget()
        self.widget = widget
        return widget

    def destroy_widget(self) -> None:
        if self.widget is not None:
            self.widget.stop_event.set()
            try:
                self.widget.root.unbind("<FocusIn>")
                self.widget.root.unbind("<FocusOut>")
                self.widget.root.unbind("<Configure>")
                for callback in self.widget.root.tk.call("after", "info"):
                    self.widget.root.after_cancel(callback)
                self.widget.root.destroy()
            except tk.TclError:
                pass
            self.widget = None

    def is_topmost(self, widget: TokenWidget) -> bool:
        hwnd = native_root_window(widget.root.winfo_id())
        return bool(self.get_style(hwnd, -20) & 0x00000008)

    def companion_for(self, owner: tk.Tk) -> TokenWidget:
        widget = self.widget
        assert widget is not None
        owner.update()
        owner_hwnd = native_root_window(owner.winfo_id())
        widget.next_process_check = float("inf")
        widget.codex_pids = {os.getpid()}
        with patch("desktop_widget.window_activity", return_value=(owner_hwnd, os.getpid(), 0)):
            self.sync_activation(widget)
        widget.root.update()
        return widget

    def above(self, first: int, second: int) -> bool:
        USER32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        USER32.GetWindow.restype = wintypes.HWND
        hwnd = first
        for _ in range(1000):
            hwnd = USER32.GetWindow(hwnd, 2)
            if hwnd == second:
                return True
            if not hwnd:
                return False
        return False

    def test_codex_activation_associates_popup_with_its_native_owner(self) -> None:
        self.create_widget({"manual_topmost": False})
        owner = tk.Tk()
        try:
            widget = self.companion_for(owner)
            USER32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            USER32.GetWindow.restype = wintypes.HWND
            self.assertEqual(
                USER32.GetWindow(native_root_window(widget.root.winfo_id()), 4),
                native_root_window(owner.winfo_id()),
                "popup must belong to Codex's window, not only attempt a one-shot raise",
            )
        finally:
            self.destroy_widget()
            owner.destroy()

    def test_later_owner_raise_does_not_cover_companion(self) -> None:
        self.create_widget({"manual_topmost": False})
        owner = tk.Tk()
        try:
            widget = self.companion_for(owner)
            owner_hwnd = native_root_window(owner.winfo_id())
            self.assertTrue(USER32.SetWindowPos(owner_hwnd, None, 0, 0, 0, 0, 0x0013))
            owner.update()
            self.assertTrue(
                self.above(native_root_window(widget.root.winfo_id()), owner_hwnd),
                "a late Codex activation must not cover its popup",
            )
            self.assertFalse(self.is_topmost(widget))
        finally:
            self.destroy_widget()
            owner.destroy()

    def test_associated_popup_can_be_covered_by_other_apps(self) -> None:
        self.create_widget({"manual_topmost": False})
        owner = tk.Tk()
        other = tk.Tk()
        try:
            widget = self.companion_for(owner)
            other.update()
            other_hwnd = native_root_window(other.winfo_id())
            self.assertTrue(USER32.SetWindowPos(other_hwnd, None, 0, 0, 0, 0, 0x0013))
            self.assertTrue(self.above(other_hwnd, native_root_window(widget.root.winfo_id())))
            self.assertFalse(self.is_topmost(widget))
        finally:
            self.destroy_widget()
            other.destroy()
            owner.destroy()

    def test_cross_process_companion_reactivation_and_minimize(self) -> None:
        fixture = r'''
import ctypes, json, queue, sys, threading, tkinter as tk
from ctypes import wintypes
u = ctypes.WinDLL("user32", use_last_error=True)
u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
u.GetAncestor.restype = wintypes.HWND
u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u.SetForegroundWindow.argtypes = [wintypes.HWND]
u.GetForegroundWindow.restype = wintypes.HWND
owner = tk.Tk()
owner.title("Companion test owner")
owner.geometry("560x302+60+60")
owner.update()
other = tk.Tk()
other.title("Companion test other app")
other.geometry("560x302+60+60")
other.update()
owner_hwnd = u.GetAncestor(owner.winfo_id(), 2)
other_hwnd = u.GetAncestor(other.winfo_id(), 2)
print(json.dumps([owner_hwnd, other_hwnd]), flush=True)
commands = queue.Queue()
def read():
    for line in sys.stdin:
        commands.put(line.strip())
    commands.put("quit")
threading.Thread(target=read, daemon=True).start()
def tick():
    try:
        command = commands.get_nowait()
    except queue.Empty:
        owner.after(10, tick)
        return
    if command == "quit":
        other.destroy()
        owner.destroy()
        return
    if command == "minimize":
        u.ShowWindow(owner_hwnd, 6)
    elif command == "restore":
        u.ShowWindow(owner_hwnd, 4)
    else:
        hwnd = owner_hwnd if command == "owner" else other_hwnd
        activated = u.SetForegroundWindow(hwnd)
        insert_after = None if activated or command == "owner" else u.GetForegroundWindow()
        u.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, 0x0013)
    print(json.dumps(command), flush=True)
    owner.after(10, tick)
owner.after(10, tick)
owner.mainloop()
'''
        child = subprocess.Popen(
            [sys.executable, "-B", "-c", fixture],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        replies: queue.Queue[str] = queue.Queue()
        reader = threading.Thread(target=lambda: [replies.put(line) for line in child.stdout], daemon=True)
        reader.start()

        def reply(timeout: float = 5) -> str:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    return replies.get_nowait()
                except queue.Empty:
                    # Cross-process z-order operations can send messages to our Tk thread.
                    if self.widget is not None:
                        self.widget.root.update()
                    time.sleep(0.01)
            self.fail("native window fixture did not reply")

        try:
            owner_hwnd, other_hwnd = json.loads(reply(10))
            widget = self.create_widget({"manual_topmost": False})
            widget.next_process_check = float("inf")
            widget.codex_pids = {child.pid}

            def command(value: str) -> None:
                child.stdin.write(value + "\n")
                child.stdin.flush()
                self.assertEqual(json.loads(reply()), value)
                widget.root.update()

            USER32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
            USER32.AllowSetForegroundWindow(child.pid)
            command("owner")
            foreground = USER32.GetForegroundWindow()
            with patch("desktop_widget.window_activity", return_value=(owner_hwnd, child.pid, 0)):
                self.sync_activation(widget)
            widget.root.update()
            self.assertEqual(USER32.GetForegroundWindow(), foreground)
            hwnd = native_root_window(widget.root.winfo_id())
            self.assertEqual(USER32.GetWindow(hwnd, 4), owner_hwnd)

            for _ in range(3):
                command("owner")
                self.assertTrue(self.above(hwnd, owner_hwnd))
                command("other")
                self.assertTrue(self.above(other_hwnd, hwnd))
            USER32.IsWindowVisible.argtypes = [wintypes.HWND]
            command("minimize")
            self.assertFalse(USER32.IsWindowVisible(hwnd))
            command("restore")
            self.assertTrue(USER32.IsWindowVisible(hwnd))
            with patch("desktop_widget.window_activity", return_value=(hwnd, os.getpid(), 0)):
                widget._close_by_user()
            widget.activation_tracker.ignore_activation_until = 0
            with patch("desktop_widget.window_activity", return_value=(owner_hwnd, child.pid, 0)):
                self.sync_activation(widget)
            widget.root.update()
            self.assertEqual(widget.root.state(), "normal")
            self.assertTrue(self.above(hwnd, owner_hwnd))
            self.assertFalse(self.is_topmost(widget))
            child.stdin.write("quit\n")
            child.stdin.flush()
            deadline = time.monotonic() + 5
            while child.poll() is None and time.monotonic() < deadline:
                widget.root.update()
                time.sleep(0.01)
            self.assertEqual(child.poll(), 0)
            widget.root.update()
            self.assertFalse(USER32.GetWindow(hwnd, 4))
            for callback in widget.root.tk.call("after", "info"):
                widget.root.after_cancel(callback)
            widget.root.unbind("<FocusIn>")
            widget.root.unbind("<FocusOut>")
            widget.root.unbind("<Configure>")
            widget.messages.put(("codex_exit", None))
            widget._drain_messages()
            USER32.IsWindow.argtypes = [wintypes.HWND]
            self.assertFalse(USER32.IsWindow(hwnd))
        finally:
            self.destroy_widget()
            if child.poll() is None:
                child.stdin.write("quit\n")
                child.stdin.flush()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            reader.join(timeout=2)
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()

    def test_legacy_automatic_pin_is_not_restored(self) -> None:
        widget = self.create_widget({"topmost": True, "theme": "light"})
        widget.root.deiconify()
        widget.root.update()
        self.assertFalse(widget.topmost)
        self.assertFalse(self.is_topmost(widget))
        self.assertEqual(widget.theme, "light")

    def test_only_manual_pin_choice_is_saved_and_restored(self) -> None:
        widget = self.create_widget({"topmost": False})
        widget._toggle_topmost()
        saved = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        self.assertIs(saved.get("manual_topmost"), True)
        self.assertEqual(saved["theme"], widget.theme)
        self.assertEqual(saved["geometry"], widget.root.geometry())
        restored = self.create_widget(saved)
        self.assertTrue(restored.topmost)
        restored._toggle_topmost()
        saved = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        self.assertIs(saved.get("manual_topmost"), False)
        self.assertFalse(self.create_widget(saved).topmost)

    def test_codex_reveal_does_not_pin_or_take_focus(self) -> None:
        widget = self.create_widget({"topmost": False})
        foreground = USER32.GetForegroundWindow()
        widget._reveal_for_codex()
        widget.root.update()
        self.assertEqual(widget.root.state(), "normal")
        self.assertFalse(widget.topmost)
        self.assertFalse(self.is_topmost(widget))
        self.assertEqual(USER32.GetForegroundWindow(), foreground)

    def test_close_then_reveal_restores_unpinned_popup(self) -> None:
        widget = self.create_widget({"topmost": False})
        widget.root.deiconify()
        widget.root.update()
        widget._close_by_user()
        self.assertEqual(widget.root.state(), "withdrawn")
        widget._reveal_for_codex()
        widget.root.update()
        self.assertEqual(widget.root.state(), "normal")
        self.assertFalse(widget.hidden_by_user)
        self.assertFalse(self.is_topmost(widget))

    def test_reveal_preserves_explicit_manual_pin(self) -> None:
        widget = self.create_widget({"manual_topmost": True})
        widget._reveal_for_codex()
        widget.root.update()
        self.assertTrue(widget.topmost)
        self.assertTrue(self.is_topmost(widget))

    def test_other_normal_window_can_cover_revealed_popup(self) -> None:
        widget = self.create_widget({"topmost": False})
        widget._reveal_for_codex()
        widget.root.update()
        other = tk.Tk()
        self.addCleanup(other.destroy)
        other.geometry("560x302+40+40")
        other.update()
        other_hwnd = native_root_window(other.winfo_id())
        widget_hwnd = native_root_window(widget.root.winfo_id())
        self.assertFalse(self.get_style(other_hwnd, -20) & 0x00000008)
        self.assertTrue(USER32.SetWindowPos(other_hwnd, None, 0, 0, 0, 0, 0x0013))
        USER32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        USER32.GetWindow.restype = wintypes.HWND
        hwnd = other_hwnd
        for _ in range(1000):
            hwnd = USER32.GetWindow(hwnd, 2)
            if not hwnd or hwnd == widget_hwnd:
                break
        self.assertEqual(hwnd, widget_hwnd, "normal windows must be able to cover the popup")


if __name__ == "__main__":
    unittest.main()
