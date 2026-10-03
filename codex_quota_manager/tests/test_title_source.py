import unittest

from codex_monitor.models import QuotaWindow
from codex_monitor.title_source import CodexThreadTitleSource


class CodexThreadTitleSourceTests(unittest.TestCase):
    def test_extract_titles_uses_thread_name_and_normalizes_whitespace(self) -> None:
        result = {
            "data": [
                {"id": "task-1", "name": " 商品筛选  "},
                {"id": "task-2", "name": "维护\nVPN"},
                {"id": "task-3", "name": None},
            ]
        }

        self.assertEqual(
            CodexThreadTitleSource._extract_titles(result),
            {"task-1": "商品筛选", "task-2": "维护 VPN"},
        )

    def test_extract_titles_rejects_unbounded_prompt_text(self) -> None:
        result = {"data": [{"id": "task-1", "name": "x" * 129}]}

        self.assertEqual(CodexThreadTitleSource._extract_titles(result), {})

    def test_extract_quota_windows_uses_live_account_snapshot(self) -> None:
        result = {
            "rateLimits": {
                "limitId": "codex",
                "primary": {
                    "usedPercent": 5,
                    "windowDurationMins": 10_080,
                    "resetsAt": 2_000_000_000,
                },
                "secondary": {
                    "usedPercent": 0,
                    "windowDurationMins": 300,
                    "resetsAt": 1_900_000_000,
                },
            }
        }

        windows = CodexThreadTitleSource._extract_quota_windows(result, observed_at=1_800_000_000)

        self.assertEqual([window.kind for window in windows], ["short", "weekly"])
        self.assertEqual([window.used_percent for window in windows], [0, 5])
        self.assertTrue(all(window.observed_at == 1_800_000_000 for window in windows))

    def test_extract_quota_windows_supports_limit_id_map(self) -> None:
        result = {
            "rateLimitsByLimitId": {
                "codex": {
                    "limitId": "codex",
                    "primary": {
                        "usedPercent": 12,
                        "windowDurationMins": 10_080,
                        "resetsAt": 2_000_000_000,
                    },
                }
            }
        }

        windows = CodexThreadTitleSource._extract_quota_windows(result, observed_at=10)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].remaining_percent, 88)

    def test_quota_snapshot_expires_to_rollout_fallback(self) -> None:
        source = CodexThreadTitleSource(".")
        source._quota_windows = [QuotaWindow("codex", 10_080, 5, 2_000, 100)]
        source._quota_updated_at = 100

        retained, retained_at = source.quota_windows(now=111)
        expired, expired_at = source.quota_windows(max_age_seconds=10, now=111)

        self.assertEqual(len(retained), 1)
        self.assertEqual(retained_at, 100)
        self.assertEqual(expired, [])
        self.assertIsNone(expired_at)

    def test_empty_account_quota_response_keeps_last_known_snapshot(self) -> None:
        source = CodexThreadTitleSource(".")
        previous = QuotaWindow("codex", 10_080, 43, 2_000, 100)
        source._quota_windows = [previous]
        source._quota_updated_at = 100
        source._request = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]

        source._refresh_account_quota(None, None)  # type: ignore[arg-type]

        windows, updated_at = source.quota_windows(now=101)
        self.assertEqual(windows, [previous])
        self.assertEqual(updated_at, 100)


if __name__ == "__main__":
    unittest.main()
