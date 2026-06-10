import unittest

from cx_reminder.cli import build_notifiers
from cx_reminder.notifiers.console import ConsoleNotifier
from cx_reminder.notifiers.windows_popup import WindowsPopupNotifier


class CliTest(unittest.TestCase):
    def test_popup_enabled_config_uses_console_and_windows_popup_only(self):
        notifiers = build_notifiers({"enable_windows_popup": True})

        self.assertEqual(type(notifiers[0]), ConsoleNotifier)
        self.assertTrue(any(isinstance(item, WindowsPopupNotifier) for item in notifiers))
        self.assertEqual(len(notifiers), 2)

    def test_popup_disabled_config_uses_console_only(self):
        notifiers = build_notifiers({"enable_windows_popup": False})

        self.assertEqual(len(notifiers), 1)
        self.assertIsInstance(notifiers[0], ConsoleNotifier)


if __name__ == "__main__":
    unittest.main()
