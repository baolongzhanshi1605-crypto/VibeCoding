from __future__ import annotations

import ctypes


class WindowsPopupNotifier:
    def send(self, title: str, content: str) -> bool:
        try:
            ctypes.windll.user32.MessageBoxW(None, content, title, 0x00001000)
            return True
        except Exception:
            return False

