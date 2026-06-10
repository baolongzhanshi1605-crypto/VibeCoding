from __future__ import annotations


class ConsoleNotifier:
    def send(self, title: str, content: str) -> bool:
        print(f"\n{title}\n{content}\n")
        return True

