"""Render a disposable fixture widget without changing the production popup."""
from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab
from budget_ui_fixture import BudgetFixture
from desktop_widget import MIN_WIDTH, TokenWidget, native_root_window


def main():
    output = Path(__file__).resolve().parents[1] / "output" / "playwright"
    output.mkdir(parents=True, exist_ok=True)
    fixture = BudgetFixture()
    with (
        patch.object(TokenWidget, "_load_preferences", return_value={"theme": "dark", "manual_topmost": False}),
        patch.object(TokenWidget, "_poll"),
        patch.object(TokenWidget, "_sync_codex_activation"),
        patch.object(TokenWidget, "_schedule_save"),
        patch.object(TokenWidget, "_save_preferences"),
    ):
        widget = TokenWidget()
        widget.root.title("Budget UI test")
        widget.root.geometry(f"{MIN_WIDTH}x302+40+60")
        try:
            for theme in ("dark", "light"):
                widget._set_theme(theme)
                for scenario in ("ready", "calibrating", "zero"):
                    fixture.scenario = scenario
                    widget._render_snapshot(fixture.snapshot())
                    widget.root.update()
                    time.sleep(0.15)
                    widget.root.update()
                    assert widget.root.winfo_width() == MIN_WIDTH
                    assert not widget.root.attributes("-topmost")
                    for label in (widget.task_label, widget.dashboard_link, widget.health_warning):
                        bottom = label.winfo_rooty() + label.winfo_height()
                        assert bottom <= widget.root.winfo_rooty() + widget.root.winfo_height(), f"{label}: clipped"
                    assert "五小时已用" in widget.task_label.cget("text")
                    rect = wintypes.RECT()
                    user32 = ctypes.windll.user32
                    user32.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
                    previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
                    try:
                        user32.GetWindowRect(native_root_window(widget.root.winfo_id()), ctypes.byref(rect))
                        ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)).save(output / f"widget-budget-{theme}-{scenario}.png")
                    finally:
                        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
            print(json.dumps({"result": "passed", "width": MIN_WIDTH, "topmost": False, "themes": 2, "scenarios": 3}))
        finally:
            widget.stop_event.set()
            widget.root.destroy()


if __name__ == "__main__":
    main()
