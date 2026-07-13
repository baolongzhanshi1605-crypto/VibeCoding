from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
import urllib.request
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
PID_PATH = RUNTIME_ROOT / "desktop_widget.pid"
DISMISSED_PATH = RUNTIME_ROOT / "desktop_widget.dismissed"
PREFERENCES_PATH = RUNTIME_ROOT / "desktop_widget.json"
STATUS_URL = "http://127.0.0.1:8790/api/status"
GEOMETRY_PATTERN = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")
MIN_WIDTH = 560
BASE_HEIGHT = 302

PAGE = "#f7f8fc"
SURFACE = "#ffffff"
INK = "#202124"
MUTED = "#5f6368"
LINE = "#dfe3e8"
BLUE = "#0b57d0"
BLUE_SOFT = "#d3e3fd"
GREEN = "#168a67"
RED = "#b3261e"
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL32.CloseHandle.restype = wintypes.BOOL


def pid_running(pid: int) -> bool:
    process = KERNEL32.OpenProcess(0x00100000, False, pid)
    if not process:
        return False
    KERNEL32.CloseHandle(process)
    return True


def singleton_available() -> bool:
    try:
        pid = int(PID_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return True
    return not pid_running(pid)


def format_tokens(value: float | int | None) -> str:
    amount = float(value or 0)
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.1f}亿"
    if amount >= 10_000:
        return f"{amount / 10_000:.1f}万"
    return f"{amount:,.0f}"


def format_countdown(epoch_seconds: int | None) -> str:
    if not epoch_seconds:
        return "未报告"
    seconds = max(0, epoch_seconds - int(time.time()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}天{hours}小时后刷新"
    if hours:
        return f"{hours}小时{minutes}分后刷新"
    return f"{minutes}分钟后刷新"


class TokenWidget:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Codex Token 检测与管控")
        self.root.configure(bg=PAGE)
        self.root.resizable(False, False)
        self._set_window_icon()
        self.root.attributes("-toolwindow", True)
        self.root.protocol("WM_DELETE_WINDOW", self._close_by_user)
        self.messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.save_after: str | None = None
        self.content_height = BASE_HEIGHT
        self.preferences = self._load_preferences()
        self.topmost = bool(self.preferences.get("topmost", True))
        self.root.attributes("-topmost", self.topmost)
        self._position_window()
        self._build()
        self.root.bind("<Configure>", self._schedule_save)
        self.root.after(100, self._drain_messages)
        threading.Thread(target=self._poll, name="token-widget-poll", daemon=True).start()

    def _font(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return ("Microsoft YaHei UI", size, weight)

    def _load_preferences(self) -> dict[str, Any]:
        try:
            value = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _position_window(self) -> None:
        self.root.update_idletasks()
        geometry = self.preferences.get("geometry")
        match = GEOMETRY_PATTERN.match(geometry) if isinstance(geometry, str) else None
        if match:
            saved_width = int(match.group(1))
            width = max(MIN_WIDTH, saved_width)
            height = self.content_height
            x = int(match.group(3)) - max(0, width - saved_width)
            y = int(match.group(4))
            self.root.geometry(f"{width}x{height}{x:+d}{y:+d}")
            return
        width, height = MIN_WIDTH, self.content_height
        x = max(16, self.root.winfo_screenwidth() - width - 28)
        self.root.geometry(f"{width}x{height}+{x}+72")

    def _set_window_icon(self) -> None:
        icon = tk.PhotoImage(width=32, height=32)
        icon.put("#ffffff", to=(0, 0, 32, 32))
        for y in range(32):
            for x in range(32):
                distance = ((x - 16) ** 2 + (y - 16) ** 2) ** 0.5
                if 9 <= distance <= 13 and not (x > 18 and 9 < y < 23):
                    icon.put(BLUE, (x, y))
                if (x - 24) ** 2 + (y - 7) ** 2 <= 9:
                    icon.put(GREEN, (x, y))
        self.window_icon = icon
        self.root.iconphoto(True, icon)

    def _build(self) -> None:
        outer = tk.Frame(self.root, bg=PAGE, padx=14, pady=11)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=PAGE)
        header.pack(fill="x")
        tk.Label(header, text="Codex Token", bg=PAGE, fg=INK, font=self._font(14, "bold")).pack(side="left")
        self.pin_button = tk.Button(
            header,
            text="置顶",
            command=self._toggle_topmost,
            relief="flat",
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2",
            font=self._font(9, "bold"),
        )
        self.pin_button.pack(side="right")
        self.status_label = tk.Label(header, text="连接中", bg=PAGE, fg=MUTED, font=self._font(9, "bold"))
        self.status_label.pack(side="right", padx=(0, 10))
        self._render_pin()

        quota = tk.Frame(outer, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, padx=10, pady=9)
        quota.pack(fill="x", pady=(9, 7))
        for column in range(3):
            quota.grid_columnconfigure(column, weight=1, uniform="quota")
        self.short_value, self.short_reset = self._quota_column(quota, 0, "短周期剩余", GREEN)
        self.week_value, self.week_reset = self._quota_column(quota, 1, "周额度剩余", BLUE)
        self.daily_value, self.daily_reset = self._quota_column(quota, 2, "今日花费", RED, value_size=18)

        metrics = tk.Frame(outer, bg=PAGE)
        metrics.pack(fill="x", pady=(1, 5))
        for column in range(4):
            metrics.grid_columnconfigure(column, weight=1, uniform="metric")
        self.active_value = self._metric_column(metrics, 0, "运行任务")
        self.token_value = self._metric_column(metrics, 1, "运行 Token")
        self.burn_value = self._metric_column(metrics, 2, "消耗速度")
        self.budget_value = self._metric_column(metrics, 3, "可用预算")

        self.task_label = tk.Label(
            outer,
            text="等待任务数据",
            anchor="w",
            justify="left",
            bg=PAGE,
            fg=INK,
            font=self._font(9),
        )
        self.task_label.pack(fill="x")
        self.health_warning = tk.Label(
            outer,
            text="注意：Token有害身心健康，请谨慎触碰！",
            anchor="w",
            bg=PAGE,
            fg=RED,
            font=self._font(9, "bold"),
        )
        self.token_plea = tk.Label(
            outer,
            text="求你了，再给我一点Token吧！",
            anchor="w",
            bg=PAGE,
            fg=BLUE,
            font=self._font(9),
        )
        self.token_plea.pack(fill="x", pady=(7, 0))
        self.health_warning.pack(fill="x", pady=(3, 0))

    def _quota_column(
        self,
        parent: tk.Frame,
        column: int,
        title: str,
        accent: str,
        value_size: int = 20,
    ) -> tuple[tk.Label, tk.Label]:
        frame = tk.Frame(parent, bg=SURFACE, padx=6)
        frame.grid(row=0, column=column, sticky="nsew")
        if column:
            frame.configure(highlightbackground=LINE, highlightthickness=0)
        tk.Label(frame, text=title, anchor="w", bg=SURFACE, fg=MUTED, font=self._font(9)).pack(fill="x")
        value = tk.Label(frame, text="--", anchor="w", bg=SURFACE, fg=accent, font=self._font(value_size, "bold"))
        value.pack(fill="x")
        reset = tk.Label(frame, text="未报告", anchor="w", bg=SURFACE, fg=MUTED, font=self._font(8))
        reset.pack(fill="x")
        return value, reset

    def _metric_column(self, parent: tk.Frame, column: int, title: str) -> tk.Label:
        frame = tk.Frame(parent, bg=PAGE, padx=3)
        frame.grid(row=0, column=column, sticky="nsew")
        value = tk.Label(frame, text="--", bg=PAGE, fg=INK, font=self._font(11, "bold"))
        value.pack()
        tk.Label(frame, text=title, bg=PAGE, fg=MUTED, font=self._font(8)).pack()
        return value

    def _toggle_topmost(self) -> None:
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self._render_pin()
        self._save_preferences()

    def _close_by_user(self) -> None:
        try:
            DISMISSED_PATH.write_text(str(int(time.time())), encoding="ascii")
        except OSError:
            pass
        self.root.destroy()

    def _render_pin(self) -> None:
        if self.topmost:
            self.pin_button.configure(text="置顶中", bg=BLUE_SOFT, fg=BLUE, activebackground=BLUE_SOFT)
        else:
            self.pin_button.configure(text="置顶", bg="#e9eef6", fg=MUTED, activebackground="#e9eef6")

    def _schedule_save(self, _event: tk.Event[Any]) -> None:
        if self.root.state() != "normal":
            return
        if self.save_after:
            self.root.after_cancel(self.save_after)
        self.save_after = self.root.after(500, self._save_preferences)

    def _save_preferences(self) -> None:
        self.save_after = None
        value = {"geometry": self.root.geometry(), "topmost": self.topmost}
        try:
            PREFERENCES_PATH.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _poll(self) -> None:
        while not self.stop_event.wait(1):
            try:
                with urllib.request.urlopen(STATUS_URL, timeout=0.9) as response:
                    payload = json.load(response)
                self.messages.put(("snapshot", payload))
            except (OSError, json.JSONDecodeError) as exc:
                self.messages.put(("error", str(exc)))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "snapshot":
                    self._render_snapshot(payload)
                else:
                    self.status_label.configure(text="连接中断", fg=RED)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_messages)

    def _render_snapshot(self, snapshot: dict[str, Any]) -> None:
        windows = {item.get("kind"): item for item in snapshot.get("quota_windows", [])}
        self._render_window(windows.get("short"), self.short_value, self.short_reset)
        self._render_window(windows.get("weekly"), self.week_value, self.week_reset)
        daily = snapshot.get("daily_usage") or {}
        self.daily_value.configure(text=format_tokens(daily.get("tokens")))
        self.daily_reset.configure(text=format_countdown(daily.get("resets_at")))

        tasks = snapshot.get("tasks", [])
        running = [task for task in tasks if task.get("status") == "running"]
        token_total = sum(int(task.get("tokens", {}).get("total_tokens") or 0) for task in running)
        burn_total = sum(float(task.get("burn_rate_tokens_per_minute") or 0) for task in running)
        budget = float(snapshot.get("budget_plan", {}).get("available_percent") or 0)

        self.active_value.configure(text=str(len(running)))
        self.token_value.configure(text=format_tokens(token_total))
        self.burn_value.configure(text=f"{format_tokens(burn_total)}/分" if burn_total else "校准中")
        self.budget_value.configure(text=f"{budget:.1f}%")

        turn_display = snapshot.get("turn_display") or {}
        display_tasks = turn_display.get("tasks") or []
        if display_tasks:
            status_names = {"running": "运行中", "waiting": "等待确认"}
            task_lines = []
            for index, task in enumerate(display_tasks, start=1):
                task_name = str(task.get("name") or "未命名任务")
                status = str(task.get("status") or "completed")
                turn_tokens = int(task.get("turn_tokens") or 0)
                if status in {"running", "waiting"}:
                    cumulative = int(task.get("cumulative_tokens") or 0)
                    status_name = status_names[status]
                    task_lines.append(
                        f"{index}. {task_name}｜{status_name}｜累计{format_tokens(cumulative)}｜本次{format_tokens(turn_tokens)} Token"
                    )
                else:
                    task_lines.append(
                        f"{index}. 本次工作：{task_name}｜已结束｜花费{format_tokens(turn_tokens)} Token"
                    )
            self.task_label.configure(text="\n".join(task_lines))
            self._resize_for_task_rows(len(task_lines))
        else:
            self.task_label.configure(text="当前没有活动任务")
            self._resize_for_task_rows()
        generated_at = int(snapshot.get("generated_at") or time.time())
        clock = datetime.fromtimestamp(generated_at).strftime("%H:%M:%S")
        self.status_label.configure(text=f"实时 · {clock}", fg=GREEN)

    def _resize_for_task_rows(self, active_rows: int = 1) -> None:
        height = BASE_HEIGHT + max(0, active_rows - 1) * 19
        if height == self.content_height:
            return
        self.content_height = height
        current_width = self.root.winfo_width()
        width = max(MIN_WIDTH, current_width)
        x = self.root.winfo_x() - max(0, width - current_width)
        self.root.geometry(f"{width}x{height}{x:+d}{self.root.winfo_y():+d}")

    @staticmethod
    def _render_window(window: dict[str, Any] | None, value: tk.Label, reset: tk.Label) -> None:
        if not window:
            value.configure(text="--")
            reset.configure(text="未报告")
            return
        value.configure(text=f"{float(window.get('remaining_percent') or 0):.0f}%")
        reset.configure(text=format_countdown(window.get("resets_at")))

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.stop_event.set()
            PID_PATH.unlink(missing_ok=True)


def main() -> int:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    if not singleton_available():
        return 0
    PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    TokenWidget().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
