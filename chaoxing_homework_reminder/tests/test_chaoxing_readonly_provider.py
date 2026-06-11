from datetime import datetime
from zoneinfo import ZoneInfo
import unittest

from cx_reminder.providers.chaoxing_readonly import (
    parse_task_timing,
    parse_work_list,
)


class ChaoxingReadonlyProviderTest(unittest.TestCase):
    def test_parse_work_list_extracts_unsubmitted_item(self):
        html = """
        <li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=1"
            aria-label="项目报告1 ; 未交">
          <p class="overHidden2 fl">项目报告1</p>
          <p class="status fl">未交</p>
        </li>
        """

        works = parse_work_list(html)

        self.assertEqual(len(works), 1)
        self.assertEqual(works[0].title, "项目报告1")
        self.assertEqual(works[0].status, "未交")
        self.assertEqual(works[0].work_id, "1")

    def test_parse_task_timing_extracts_due_time(self):
        html = "作答时间: 06-05 12:51 至 06-13 13:51"
        tz = ZoneInfo("Asia/Shanghai")

        timing = parse_task_timing(html, current_year=2026, timezone=tz)

        self.assertEqual(timing.due_at, datetime(2026, 6, 13, 13, 51, tzinfo=tz))
        self.assertEqual(timing.context, "作答时间: 06-05 12:51 至 06-13 13:51")

    def test_parse_task_timing_handles_start_only_without_due(self):
        html = "作答开始时间: 05-26 12:50"

        timing = parse_task_timing(
            html,
            current_year=2026,
            timezone=ZoneInfo("Asia/Shanghai"),
        )

        self.assertIsNone(timing.due_at)
        self.assertEqual(timing.context, "作答开始时间: 05-26 12:50")


if __name__ == "__main__":
    unittest.main()
