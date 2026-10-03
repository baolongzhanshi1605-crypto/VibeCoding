from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import queue
import re
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from ctypes import wintypes
from datetime import datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any, Callable

from codex_link import CodexExitGuard, codex_desktop_pids, codex_desktop_running, process_entries


PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
PID_PATH = RUNTIME_ROOT / "desktop_widget.pid"
DISMISSED_PATH = RUNTIME_ROOT / "desktop_widget.dismissed"
PREFERENCES_PATH = RUNTIME_ROOT / "desktop_widget.json"
STATUS_URL = "http://127.0.0.1:8790/api/status"
DASHBOARD_URL = "http://127.0.0.1:8790/display"
GEOMETRY_PATTERN = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")
MIN_WIDTH = 560
BASE_HEIGHT = 302
DWM_USE_IMMERSIVE_DARK_MODE = 20
DWM_BORDER_COLOR = 34
DWM_CAPTION_COLOR = 35
DWM_TEXT_COLOR = 36
GA_ROOT = 2
GA_ROOTOWNER = 3
GW_OWNER = 4
GWLP_HWNDPARENT = -8
TITLEBAR_REAPPLY_DELAY_MS = 60

PALETTES = {
    "light": {
        "page": "#f7f8fc",
        "surface": "#ffffff",
        "surface_soft": "#e9eef6",
        "ink": "#202124",
        "muted": "#5f6368",
        "line": "#dfe3e8",
        "blue": "#0b57d0",
        "blue_soft": "#d3e3fd",
        "green": "#168a67",
        "red": "#b3261e",
        "amber": "#8a5a00",
    },
    "dark": {
        "page": "#101214",
        "surface": "#181b1f",
        "surface_soft": "#24292f",
        "ink": "#f2f4f7",
        "muted": "#aab0b8",
        "line": "#343a40",
        "blue": "#78a9ff",
        "blue_soft": "#243853",
        "green": "#43d19e",
        "red": "#ff8178",
        "amber": "#f0b95a",
    },
}
PAGE = PALETTES["dark"]["page"]
SURFACE = PALETTES["dark"]["surface"]
SURFACE_SOFT = PALETTES["dark"]["surface_soft"]
INK = PALETTES["dark"]["ink"]
MUTED = PALETTES["dark"]["muted"]
LINE = PALETTES["dark"]["line"]
BLUE = PALETTES["dark"]["blue"]
BLUE_SOFT = PALETTES["dark"]["blue_soft"]
GREEN = PALETTES["dark"]["green"]
RED = PALETTES["dark"]["red"]
AMBER = PALETTES["dark"]["amber"]
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL32.CloseHandle.restype = wintypes.BOOL
USER32 = ctypes.WinDLL("user32", use_last_error=True)
USER32.GetForegroundWindow.restype = wintypes.HWND
USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
USER32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
USER32.SetWindowPos.restype = wintypes.BOOL
USER32.GetAsyncKeyState.argtypes = [ctypes.c_int]
USER32.GetAsyncKeyState.restype = wintypes.SHORT
USER32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
USER32.GetAncestor.restype = wintypes.HWND
USER32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
USER32.GetWindow.restype = wintypes.HWND
SET_WINDOW_LONG_PTR = getattr(USER32, "SetWindowLongPtrW", USER32.SetWindowLongW)
SET_WINDOW_LONG_PTR.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
SET_WINDOW_LONG_PTR.restype = ctypes.c_ssize_t


def associate_native_window(hwnd: int, owner: int) -> None:
    if USER32.GetWindow(hwnd, GW_OWNER) == owner:
        return
    ctypes.set_last_error(0)
    previous = SET_WINDOW_LONG_PTR(hwnd, GWLP_HWNDPARENT, owner)
    error = ctypes.get_last_error()
    if previous == 0 and error:
        raise ctypes.WinError(error)


def window_activity() -> tuple[int, int, int]:
    hwnd = USER32.GetForegroundWindow()
    pid = wintypes.DWORD()
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(hwnd or 0), pid.value, USER32.GetAsyncKeyState(0x01)


class CodexActivationTracker:
    def __init__(self) -> None:
        self.last_window: int | None = None
        self.last_button_down = False
        self.ignore_activation_until = 0.0

    def remember(self, activity: tuple[int, int, int]) -> None:
        self.last_window, _pid, buttons = activity
        self.last_button_down = bool(buttons & 0x8000)

    def dismiss(self, activity: tuple[int, int, int], now: float) -> None:
        self.remember(activity)
        self.ignore_activation_until = now + 0.25

    def should_reveal(self, activity: tuple[int, int, int], codex_pids: set[int], hidden: bool, now: float) -> bool:
        hwnd, pid, buttons = activity
        activated = hwnd != self.last_window
        clicked = bool(buttons & 1) or (bool(buttons & 0x8000) and not self.last_button_down)
        self.remember(activity)
        if hidden and now < self.ignore_activation_until:
            activated = False
        return pid in codex_pids and (clicked or activated)


def palette_for(theme: str | None) -> dict[str, str]:
    return PALETTES["light" if theme == "light" else "dark"]


def apply_palette(theme: str | None) -> None:
    global PAGE, SURFACE, SURFACE_SOFT, INK, MUTED, LINE, BLUE, BLUE_SOFT, GREEN, RED, AMBER
    palette = palette_for(theme)
    PAGE = palette["page"]
    SURFACE = palette["surface"]
    SURFACE_SOFT = palette["surface_soft"]
    INK = palette["ink"]
    MUTED = palette["muted"]
    LINE = palette["line"]
    BLUE = palette["blue"]
    BLUE_SOFT = palette["blue_soft"]
    GREEN = palette["green"]
    RED = palette["red"]
    AMBER = palette["amber"]


def colorref(color: str) -> int:
    value = color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def titlebar_attributes(theme: str | None) -> tuple[tuple[int, int], ...]:
    palette = palette_for(theme)
    return (
        (DWM_USE_IMMERSIVE_DARK_MODE, int(theme != "light")),
        (DWM_BORDER_COLOR, colorref(palette["line"])),
        (DWM_CAPTION_COLOR, colorref(palette["page"])),
        (DWM_TEXT_COLOR, colorref(palette["ink"])),
    )


def native_root_window(
    hwnd: int,
    resolver: Callable[[int], int] | None = None,
) -> int:
    """Return the top-level native window that owns the title bar."""
    if resolver is not None:
        return resolver(hwnd) or hwnd

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_ancestor = user32.GetAncestor
        get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
        get_ancestor.restype = wintypes.HWND
        resolved = get_ancestor(wintypes.HWND(hwnd), GA_ROOT)
    except (AttributeError, OSError):
        return hwnd

    return int(getattr(resolved, "value", resolved) or hwnd)


def apply_native_titlebar_theme(
    hwnd: int,
    theme: str | None,
    setter: Callable[[int, int, int], int] | None = None,
    window_resolver: Callable[[int], int] | None = None,
) -> bool:
    native_hwnd = native_root_window(hwnd, window_resolver)

    if setter is None:
        def setter(window: int, attribute: int, value: int) -> int:
            native_value = ctypes.c_int(value)
            return ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(window),
                attribute,
                ctypes.byref(native_value),
                ctypes.sizeof(native_value),
            )

    try:
        results = [setter(native_hwnd, attribute, value) for attribute, value in titlebar_attributes(theme)]
    except (AttributeError, OSError):
        return False
    return all(result == 0 for result in results)


def bind_titlebar_theme_sync(root: Any, refresh: Callable[[], None]) -> None:
    def resync(_event: object) -> None:
        root.after_idle(refresh)
        root.after(TITLEBAR_REAPPLY_DELAY_MS, refresh)

    for sequence in ("<FocusIn>", "<FocusOut>"):
        root.bind(sequence, resync, add="+")


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
    return pid == os.getpid() or not pid_running(pid)


def format_tokens(value: float | int | None) -> str:
    amount = float(value or 0)
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.1f}亿"
    if amount >= 10_000:
        return f"{amount / 10_000:.1f}万"
    return f"{amount:,.0f}"


def format_exact_tokens(value: int | None) -> str:
    return f"{int(value or 0):,} Token"


def format_usage_streak(streak: dict[str, Any] | None) -> tuple[str, str]:
    streak = streak or {}
    days = max(0, int(streak.get("days") or 0))
    tokens = max(0, int(streak.get("tokens") or 0))
    return f"{days} 天", f"累计 {format_tokens(tokens)} Token"


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


def format_quota_wait(freshness: str | None) -> str:
    if freshness == "expired":
        return "等待新周期上报"
    return "等待 Codex 上报"


def open_dashboard() -> None:
    webbrowser.open(DASHBOARD_URL, new=2)


def format_budget_state(state: str | None) -> str:
    return "校准中" if state == "calibrating" else "等待额度"


def format_budget_forecast(budget: dict[str, Any]) -> str:
    forecast = budget.get("forecast")
    if forecast == "exhausts":
        minutes = max(1, math.ceil(float(budget.get("seconds_remaining") or 0) / 60))
        duration = f"{minutes // 60}小时{minutes % 60}分" if minutes >= 60 else f"{minutes}分钟"
        return f"约{duration}耗尽"
    return {
        "exhausted": "建议预算已用尽",
        "waiting": "等待中",
        "unknown_rate": "速度校准中",
        "after_reset": "刷新前充足",
    }.get(forecast, format_budget_state(forecast))


def format_task_activity_line(index: int, task: dict[str, Any]) -> str:
    task_name = str(task.get("name") or "未命名任务")
    status = str(task.get("status") or "completed")
    turn_tokens = int(task.get("turn_tokens") or 0)
    if status in {"running", "waiting"}:
        status_name = {"running": "运行中", "waiting": "等待确认"}[status]
        cumulative = int(task.get("cumulative_tokens") or 0)
        line = (
            f"{index}. {task_name}｜{status_name}｜任务累计{format_tokens(cumulative)}"
            f"｜本轮消耗{format_tokens(turn_tokens)} Token"
        )
        budget = task.get("token_budget")
        if isinstance(budget, dict):
            remaining = budget.get("remaining_tokens")
            available = format_tokens(remaining) if remaining is not None else format_budget_state(budget.get("forecast"))
            used = budget.get("window_used_tokens")
            line += (
                f"\n   五小时已用{format_tokens(used) if used is not None else '--'}"
                f"｜可用估算{available}｜{format_budget_forecast(budget)}"
            )
        return line
    return f"{index}. 本轮工作：{task_name}｜已结束｜本轮消耗{format_tokens(turn_tokens)} Token"


class TokenWidget:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Codex Token 检测与管控")
        self.messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.exit_guard = CodexExitGuard()
        self.connection_failed = False
        self.hidden_by_user = False
        self.activation_tracker = CodexActivationTracker()
        self.codex_pids: set[int] = set()
        self.next_process_check = 0.0
        self.status_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.save_after: str | None = None
        self.content_height = BASE_HEIGHT
        self.last_snapshot: dict[str, Any] | None = None
        self.preferences = self._load_preferences()
        self.theme = "light" if self.preferences.get("theme") == "light" else "dark"
        apply_palette(self.theme)
        self.root.configure(bg=PAGE)
        self.root.resizable(False, False)
        self._set_window_icon()
        self.root.attributes("-toolwindow", True)
        self.root.protocol("WM_DELETE_WINDOW", self._close_by_user)
        # The legacy key also contains pins forced by automatic activation.
        self.topmost = self.preferences.get("manual_topmost") is True
        self.root.attributes("-topmost", self.topmost)
        self._position_window()
        self._build()
        self._set_titlebar_theme()
        bind_titlebar_theme_sync(self.root, self._apply_titlebar_theme)
        self.root.bind("<Configure>", self._schedule_save)
        self.root.after(100, self._drain_messages)
        self.root.after(100, self._sync_codex_activation)
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
            width = MIN_WIDTH
            height = self.content_height
            x = int(match.group(3)) + saved_width - width
            y = int(match.group(4))
            self.root.geometry(f"{width}x{height}{x:+d}{y:+d}")
            return
        width, height = MIN_WIDTH, self.content_height
        x = max(16, self.root.winfo_screenwidth() - width - 28)
        self.root.geometry(f"{width}x{height}+{x}+72")

    def _set_window_icon(self) -> None:
        icon = tk.PhotoImage(width=32, height=32)
        icon.put(SURFACE, to=(0, 0, 32, 32))
        for y in range(32):
            for x in range(32):
                distance = ((x - 16) ** 2 + (y - 16) ** 2) ** 0.5
                if 9 <= distance <= 13 and not (x > 18 and 9 < y < 23):
                    icon.put(BLUE, (x, y))
                if (x - 24) ** 2 + (y - 7) ** 2 <= 9:
                    icon.put(GREEN, (x, y))
        self.window_icon = icon
        self.root.iconphoto(True, icon)

    def _set_titlebar_theme(self) -> None:
        self.root.after_idle(self._apply_titlebar_theme)

    def _apply_titlebar_theme(self) -> None:
        try:
            apply_native_titlebar_theme(self.root.winfo_id(), self.theme)
        except tk.TclError:
            pass

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
        theme_control = tk.Frame(
            header,
            bg=PAGE,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=1,
            pady=1,
        )
        theme_control.pack(side="right", padx=(0, 8))
        self.theme_buttons: dict[str, tk.Button] = {}
        for theme, label in (("light", "日间"), ("dark", "夜间")):
            button = tk.Button(
                theme_control,
                text=label,
                command=lambda value=theme: self._set_theme(value),
                relief="flat",
                bd=0,
                padx=5,
                pady=2,
                cursor="hand2",
                font=self._font(8, "bold"),
            )
            button.pack(side="left")
            self.theme_buttons[theme] = button
        self.status_label = tk.Label(header, text="连接中", bg=PAGE, fg=MUTED, font=self._font(9, "bold"))
        self.status_label.pack(side="right", padx=(0, 10))
        self._render_pin()
        self._render_theme()

        quota = tk.Frame(outer, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, padx=4, pady=3)
        quota.pack(fill="x", pady=(9, 7))
        for column in range(4):
            quota.grid_columnconfigure(column, weight=1, uniform="quota")
        self.streak_value, self.streak_total = self._quota_column(quota, 0, "连续使用", GREEN)
        self.short_value, self.short_reset = self._quota_column(quota, 1, "五小时额度剩余", BLUE, value_size=18)
        self.week_value, self.week_reset = self._quota_column(quota, 2, "周额度剩余", BLUE, value_size=18)
        self.daily_value, self.daily_reset = self._quota_column(quota, 3, "今日花费", RED, value_size=18)
        self.daily_detail = tk.Label(
            self.daily_value.master,
            text="0 Token",
            anchor="w",
            bg=SURFACE,
            fg=MUTED,
            font=self._font(8),
        )
        self.daily_detail.pack(fill="x", before=self.daily_reset)

        metrics = tk.Frame(outer, bg=PAGE)
        metrics.pack(fill="x", pady=(1, 5))
        for column in range(5):
            metrics.grid_columnconfigure(column, weight=1, uniform="metric")
        self.active_value = self._metric_column(metrics, 0, "运行任务")
        self.token_value = self._metric_column(metrics, 1, "当前任务累计")
        self.burn_value = self._metric_column(metrics, 2, "消耗速度")
        self.budget_value = self._metric_column(metrics, 3, "预算估算")
        self.weekly_spend_value = self._metric_column(metrics, 4, "本周消耗")

        self.task_label = tk.Label(
            outer,
            text="等待任务数据",
            anchor="w",
            justify="left",
            bg=PAGE,
            fg=INK,
            font=self._font(9),
            wraplength=MIN_WIDTH - 36,
        )
        self.task_label.pack(fill="x")
        footer = tk.Frame(outer, bg=PAGE)
        footer.pack(fill="x", pady=(7, 0))
        footer_messages = tk.Frame(footer, bg=PAGE)
        footer_messages.pack(side="left", fill="x", expand=True)
        self.health_warning = tk.Label(
            footer_messages,
            text="注意：Token有害身心健康，请谨慎触碰！",
            anchor="w",
            bg=PAGE,
            fg=RED,
            font=self._font(9, "bold"),
        )
        self.token_plea = tk.Label(
            footer_messages,
            text="求你了，再给我一点Token吧！",
            anchor="w",
            bg=PAGE,
            fg=BLUE,
            font=self._font(9),
        )
        self.token_plea.pack(fill="x")
        self.health_warning.pack(fill="x", pady=(3, 0))
        self.dashboard_link = tk.Button(
            footer,
            text="打开网页版",
            command=open_dashboard,
            relief="flat",
            bd=0,
            padx=0,
            pady=0,
            bg=PAGE,
            fg=BLUE,
            activebackground=PAGE,
            activeforeground=BLUE,
            cursor="hand2",
            font=self._font(9, "bold"),
        )
        self.dashboard_link.pack(side="right", anchor="s", padx=(10, 0))

    def _quota_column(
        self,
        parent: tk.Frame,
        column: int,
        title: str,
        accent: str,
        value_size: int = 20,
    ) -> tuple[tk.Label, tk.Label]:
        frame = tk.Frame(parent, bg=SURFACE, padx=3)
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

    def _set_theme(self, theme: str) -> None:
        next_theme = "light" if theme == "light" else "dark"
        if next_theme == self.theme:
            return
        self.theme = next_theme
        apply_palette(self.theme)
        self.root.configure(bg=PAGE)
        self._set_window_icon()
        for child in self.root.winfo_children():
            child.destroy()
        self._build()
        self._set_titlebar_theme()
        if self.last_snapshot:
            self._render_snapshot(self.last_snapshot)
        self._save_preferences()

    def _close_by_user(self) -> None:
        self._save_preferences()
        self.hidden_by_user = True
        self.root.withdraw()
        self.activation_tracker.dismiss(window_activity(), time.monotonic())

    def _sync_codex_activation(self) -> None:
        try:
            now = time.monotonic()
            if now >= self.next_process_check:
                self.next_process_check = now + 1
                self.codex_pids = codex_desktop_pids(process_entries())
            activity = window_activity()
            if self.activation_tracker.should_reveal(activity, self.codex_pids, self.hidden_by_user, now):
                owner = int(USER32.GetAncestor(activity[0], GA_ROOTOWNER) or activity[0])
                owner_pid = wintypes.DWORD()
                USER32.GetWindowThreadProcessId(owner, ctypes.byref(owner_pid))
                if owner_pid.value in self.codex_pids:
                    self._reveal_for_codex(owner)
        except OSError:
            self.activation_tracker.last_window = None
            logging.exception("could not check Codex window activity")
        self.root.after(100, self._sync_codex_activation)

    def _reveal_for_codex(self, owner_hwnd: int | None = None) -> None:
        if self.hidden_by_user or self.root.state() != "normal":
            self.root.deiconify()
        self.hidden_by_user = False
        hwnd = native_root_window(self.root.winfo_id())
        if owner_hwnd:
            # Ownership keeps us above Codex even if its activation raises it again.
            associate_native_window(hwnd, owner_hwnd)
        # Raise within the chosen stacking band without taking Codex's focus.
        insert_after = wintypes.HWND(-1 if self.topmost else 0)
        if not USER32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, 0x0013):
            raise ctypes.WinError(ctypes.get_last_error())
        self._render_pin()

    def _render_pin(self) -> None:
        if self.topmost:
            self.pin_button.configure(text="置顶中", bg=BLUE_SOFT, fg=BLUE, activebackground=BLUE_SOFT)
        else:
            self.pin_button.configure(text="置顶", bg=SURFACE_SOFT, fg=MUTED, activebackground=SURFACE_SOFT)

    def _render_theme(self) -> None:
        for theme, button in self.theme_buttons.items():
            active = theme == self.theme
            button.configure(
                bg=BLUE_SOFT if active else SURFACE_SOFT,
                fg=BLUE if active else MUTED,
                activebackground=BLUE_SOFT if active else SURFACE_SOFT,
                activeforeground=BLUE if active else INK,
            )

    def _schedule_save(self, _event: tk.Event[Any]) -> None:
        if self.root.state() != "normal":
            return
        if self.save_after:
            self.root.after_cancel(self.save_after)
        self.save_after = self.root.after(500, self._save_preferences)

    def _save_preferences(self) -> None:
        self.save_after = None
        value = {"geometry": self.root.geometry(), "manual_topmost": self.topmost, "theme": self.theme}
        try:
            PREFERENCES_PATH.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _poll(self) -> None:
        while not self.stop_event.wait(1):
            try:
                if self.exit_guard.should_exit(codex_desktop_running(), time.monotonic()):
                    self.messages.put(("codex_exit", None))
                    return
            except OSError:
                self.exit_guard.should_exit(None, time.monotonic())
            try:
                with self.status_opener.open(STATUS_URL, timeout=2) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise ValueError("status response must be a JSON object")
                self.messages.put(("snapshot", payload))
            except (OSError, ValueError, HTTPException) as exc:
                self.messages.put(("error", str(exc)))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "codex_exit":
                    logging.info("Codex desktop exited; closing popup")
                    self.root.destroy()
                    return
                if kind == "snapshot":
                    try:
                        self._render_snapshot(payload)
                    except (ValueError, TypeError, AttributeError):
                        logging.exception("could not render status snapshot")
                        self.status_label.configure(text="数据重试中", fg=AMBER)
                        continue
                    if self.connection_failed:
                        logging.info("local dashboard connection restored")
                    self.connection_failed = False
                else:
                    if not self.connection_failed:
                        logging.warning("local dashboard unavailable: %s", payload)
                    self.connection_failed = True
                    self.status_label.configure(text="服务重连中", fg=AMBER)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_messages)

    def _render_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.last_snapshot = snapshot
        windows = {item.get("kind"): item for item in snapshot.get("quota_windows", [])}
        short_window = windows.get("short")
        weekly_window = windows.get("weekly")
        streak_value, streak_total = format_usage_streak(snapshot.get("usage_streak"))
        self.streak_value.configure(text=streak_value, fg=GREEN)
        self.streak_total.configure(text=streak_total, fg=MUTED)
        short_stale = self._render_window(short_window, self.short_value, self.short_reset, BLUE)
        weekly_stale = self._render_window(weekly_window, self.week_value, self.week_reset, BLUE)
        daily = snapshot.get("daily_usage") or {}
        self.daily_value.configure(text=format_tokens(daily.get("tokens")))
        self.daily_detail.configure(text=format_exact_tokens(daily.get("tokens")))
        self.daily_reset.configure(text=format_countdown(daily.get("resets_at")))
        weekly_usage = snapshot.get("weekly_usage") or {}
        weekly_tokens = weekly_usage.get("tokens")
        self.weekly_spend_value.configure(
            text=format_tokens(weekly_tokens)
            if weekly_tokens is not None and not weekly_usage.get("is_stale")
            else "--"
        )

        tasks = snapshot.get("tasks", [])
        running = [task for task in tasks if task.get("status") in {"running", "waiting"}]
        token_total = sum(int(task.get("tokens", {}).get("total_tokens") or 0) for task in running)
        burn_total = sum(float(task.get("burn_rate_tokens_per_minute") or 0) for task in running)
        budget_plan = snapshot.get("budget_plan", {}).get("token_budget", {})
        budget = budget_plan.get("available_tokens")

        self.active_value.configure(text=str(len(running)))
        self.token_value.configure(text=format_tokens(token_total))
        self.burn_value.configure(text=f"{format_tokens(burn_total)}/分" if burn_total else "校准中")
        self.budget_value.configure(
            text=format_tokens(budget) if budget is not None else format_budget_state(budget_plan.get("state"))
        )

        turn_display = snapshot.get("turn_display") or {}
        display_tasks = turn_display.get("tasks") or []
        if display_tasks:
            task_lines = [
                format_task_activity_line(index, task)
                for index, task in enumerate(display_tasks, start=1)
            ]
            self.task_label.configure(text="\n".join(task_lines), wraplength=max(MIN_WIDTH, self.root.winfo_width()) - 36)
            self.root.update_idletasks()
            self._resize_for_task_rows(math.ceil(self.task_label.winfo_reqheight() / 19))
        else:
            self.task_label.configure(text="当前没有活动任务")
            self._resize_for_task_rows()
        generated_at = int(snapshot.get("generated_at") or time.time())
        clock = datetime.fromtimestamp(generated_at).strftime("%H:%M:%S")
        if short_stale or weekly_stale:
            self.status_label.configure(text=f"额度待上报 · {clock}", fg=AMBER)
        elif not windows:
            self.status_label.configure(text=f"额度未报告 · {clock}", fg=MUTED)
        else:
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
    def _render_window(
        window: dict[str, Any] | None,
        value: tk.Label,
        reset: tk.Label,
        accent: str,
    ) -> bool:
        if not window:
            value.configure(text="--", fg=MUTED)
            reset.configure(text="未报告", fg=MUTED)
            return False
        remaining = float(window.get("remaining_percent") or 0)
        if window.get("is_stale"):
            value.configure(text=f"上次{remaining:.0f}%", fg=MUTED)
            reset.configure(text=format_quota_wait(window.get("freshness")), fg=AMBER)
            return True
        value.configure(text=f"{remaining:.0f}%", fg=accent)
        reset.configure(text=format_countdown(window.get("resets_at")), fg=MUTED)
        return False

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.stop_event.set()
            PID_PATH.unlink(missing_ok=True)


def main() -> int:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=RUNTIME_ROOT / "desktop_widget.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    if not singleton_available():
        return 0
    PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    TokenWidget().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
