import unittest

from codex_link import is_codex_desktop_tree


class CodexLinkTests(unittest.TestCase):
    def test_detects_codex_app_server_parented_by_desktop(self) -> None:
        entries = [
            ("chatgpt.exe", 100, 10),
            ("codex.exe", 200, 100),
            ("codex-code-mode-host.exe", 300, 200),
        ]
        self.assertTrue(is_codex_desktop_tree(entries))

    def test_ignores_standalone_codex_cli(self) -> None:
        entries = [
            ("powershell.exe", 100, 10),
            ("codex.exe", 200, 100),
        ]
        self.assertFalse(is_codex_desktop_tree(entries))

    def test_requires_codex_child(self) -> None:
        self.assertFalse(is_codex_desktop_tree([("chatgpt.exe", 100, 10)]))


if __name__ == "__main__":
    unittest.main()
