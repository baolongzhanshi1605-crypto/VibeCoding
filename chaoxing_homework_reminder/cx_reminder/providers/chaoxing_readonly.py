from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import html as html_lib
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

from ..edge_cookies import load_cookie_header
from ..models import Assignment
from ..readonly_http import ReadOnlyHttpClient


@dataclass(frozen=True)
class WorkItem:
    title: str
    status: str
    task_url: str
    work_id: str


@dataclass(frozen=True)
class TaskTiming:
    due_at: datetime | None
    context: str


@dataclass(frozen=True)
class CourseCard:
    name: str
    href: str
    course_id: str
    class_id: str
    cpi: str


class ChaoxingReadOnlyProvider:
    def __init__(
        self,
        edge_profile_path: Path,
        course_cache_path: Path,
        cache_dir: Path,
        timezone: ZoneInfo,
        current_year: int,
        request_delay_seconds: float = 0.2,
    ) -> None:
        self.edge_profile_path = edge_profile_path
        self.course_cache_path = course_cache_path
        self.cache_dir = cache_dir
        self.timezone = timezone
        self.current_year = current_year
        self.request_delay_seconds = request_delay_seconds
        self.http = ReadOnlyHttpClient(timeout=25)

    def fetch_assignments(self) -> list[Assignment]:
        cookie_header = load_cookie_header(
            self.edge_profile_path,
            ["chaoxing.com", "xuexitong.com"],
        )
        headers = {
            "Cookie": cookie_header,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            ),
            "Referer": "https://mooc1-1.chaoxing.com/visit/interaction",
        }

        assignments: list[Assignment] = []
        for course in load_course_cards(self.course_cache_path):
            middle_html, middle_url = self._get_text(course.href, headers)
            save_debug_file(
                self.cache_dir / f"middle_{course.course_id}_{course.class_id}.html",
                middle_html,
            )
            work_url = build_work_list_url(middle_html)
            if not work_url:
                continue

            work_headers = dict(headers)
            work_headers["Referer"] = middle_url
            work_html, _work_url = self._get_text(work_url, work_headers)
            save_debug_file(
                self.cache_dir / f"work_{course.course_id}_{course.class_id}.html",
                work_html,
            )

            for work in parse_work_list(work_html):
                if not is_unsubmitted_status(work.status):
                    continue
                task_html, _task_url = self._get_text(work.task_url, work_headers)
                save_debug_file(self.cache_dir / f"task_{work.work_id}.html", task_html)
                timing = parse_task_timing(
                    task_html,
                    current_year=self.current_year,
                    timezone=self.timezone,
                )
                due_at = timing.due_at
                title = work.title
                if due_at is None:
                    due_at = datetime.now(self.timezone) + timedelta(hours=24)
                    title = f"{title} [未显示截止时间]"
                assignments.append(
                    Assignment(
                        assignment_id=f"chaoxing:{work.work_id}",
                        course=course.name,
                        title=title,
                        due_at=due_at,
                        submitted=False,
                    )
                )
        return assignments

    def _get_text(self, url: str, headers: dict[str, str]) -> tuple[str, str]:
        time.sleep(self.request_delay_seconds)
        with self.http.get(url, headers=headers) as response:
            body = response.read()
            final_url = response.geturl()
        return body.decode("utf-8", errors="replace"), final_url


def load_course_cards(path: Path) -> list[CourseCard]:
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    cards: list[CourseCard] = []
    seen = set()
    for item in raw_items:
        attrs = item.get("attrs", {})
        course_id = attrs.get("courseid", "")
        class_id = attrs.get("clazzid", "")
        cpi = attrs.get("personid", "")
        links = item.get("links") or []
        original_text = item.get("text", "")
        raw_text = normalize_spaces(original_text)
        if not course_id or not class_id or not cpi or not links:
            continue
        if normalize_compact(raw_text).startswith("课程已结束"):
            continue
        key = (course_id, class_id)
        if key in seen:
            continue
        seen.add(key)
        name = first_text_line(original_text) or course_id
        cards.append(
            CourseCard(
                name=name,
                href=links[0]["href"],
                course_id=course_id,
                class_id=class_id,
                cpi=cpi,
            )
        )
    return cards


def build_work_list_url(middle_html: str) -> str | None:
    if "title=\"作业\"" not in middle_html and "dataname=\"zy\"" not in middle_html:
        return None
    course_id = hidden_value(middle_html, "courseid")
    class_id = hidden_value(middle_html, "clazzid")
    cpi = hidden_value(middle_html, "cpi")
    stuenc = hidden_value(middle_html, "enc")
    work_enc = hidden_value(middle_html, "workEnc")
    t_value = hidden_value(middle_html, "t")
    if not all([course_id, class_id, cpi, stuenc, work_enc]):
        return None
    params = {
        "courseId": course_id,
        "classId": class_id,
        "cpi": cpi,
        "ut": "s",
        "stuenc": stuenc,
        "enc": work_enc,
    }
    if t_value:
        params["t"] = t_value
    return "https://mooc1.chaoxing.com/mooc2/work/list?" + urlencode(params)


def parse_work_list(work_html: str) -> list[WorkItem]:
    works: list[WorkItem] = []
    for match in re.finditer(r"<li\b(?P<attrs>[^>]*)>(?P<body>.*?)</li>", work_html, re.S | re.I):
        attrs = match.group("attrs")
        body = match.group("body")
        if "work/task?" not in attrs and "work/task?" not in body:
            continue

        task_url_match = re.search(r"data=[\"']([^\"']*work/task\?[^\"']*)", attrs)
        task_url = html_lib.unescape(task_url_match.group(1)) if task_url_match else ""
        query = parse_qs(urlparse(task_url).query)
        work_id = query.get("workId", [""])[0]

        aria = re.search(r"aria-label=[\"']([^\"']*)", attrs)
        title = ""
        status = ""
        if aria:
            parts = [part.strip() for part in html_lib.unescape(aria.group(1)).split(";")]
            title = parts[0] if parts else ""
            status = parts[1] if len(parts) > 1 else ""
        if not title:
            title = extract_class_text(body, "overHidden2")
        if not status:
            status = extract_class_text(body, "status")
        works.append(
            WorkItem(
                title=normalize_spaces(title),
                status=normalize_compact(status),
                task_url=task_url,
                work_id=work_id,
            )
        )
    return works


def parse_task_timing(
    task_html: str,
    current_year: int,
    timezone: ZoneInfo,
) -> TaskTiming:
    plain = plain_text(task_html)
    range_pattern = (
        r"作答时间:\s*(\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})"
        r"\s*至\s*(\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})"
    )
    range_match = re.search(range_pattern, plain)
    if range_match:
        due_at = parse_month_day_time(range_match.group(2), current_year, timezone)
        return TaskTiming(due_at=due_at, context=range_match.group(0))

    start_match = re.search(r"作答开始时间:\s*(\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})", plain)
    if start_match:
        return TaskTiming(due_at=None, context=start_match.group(0))

    return TaskTiming(due_at=None, context="")


def parse_month_day_time(value: str, year: int, timezone: ZoneInfo) -> datetime:
    parsed = datetime.strptime(f"{year}-{value}", "%Y-%m-%d %H:%M")
    return parsed.replace(tzinfo=timezone)


def is_unsubmitted_status(status: str) -> bool:
    compact = normalize_compact(status)
    return compact.startswith("未")


def hidden_value(html: str, element_id: str) -> str:
    match = re.search(
        r'id=["\']'
        + re.escape(element_id)
        + r'["\'][^>]*value=["\']([^"\']*)',
        html,
    )
    return html_lib.unescape(match.group(1)) if match else ""


def extract_class_text(fragment: str, class_name: str) -> str:
    match = re.search(
        r"<p[^>]*class=[\"'][^\"']*"
        + re.escape(class_name)
        + r"[^\"']*[\"'][^>]*>(.*?)</p>",
        fragment,
        re.S | re.I,
    )
    return plain_text(match.group(1)) if match else ""


def plain_text(src: str) -> str:
    src = re.sub(r"<script.*?</script>", " ", src, flags=re.S | re.I)
    src = re.sub(r"<style.*?</style>", " ", src, flags=re.S | re.I)
    src = re.sub(r"<[^>]+>", " ", src)
    return normalize_spaces(html_lib.unescape(src))


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def normalize_compact(value: str) -> str:
    return re.sub(r"\s+", "", html_lib.unescape(value or "")).strip()


def first_text_line(value: str) -> str:
    for line in html_lib.unescape(value or "").splitlines():
        line = normalize_spaces(line)
        if line:
            return line
    return ""


def save_debug_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
