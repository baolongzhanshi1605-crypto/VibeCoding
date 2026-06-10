from __future__ import annotations

from datetime import datetime

from ..models import ReminderDecision


def format_reminder_message(decision: ReminderDecision, now: datetime) -> str:
    assignment = decision.assignment
    seconds_left = int((assignment.due_at - now).total_seconds())
    if seconds_left < 0:
        remaining = "已截止"
    else:
        minutes = seconds_left // 60
        hours, rest_minutes = divmod(minutes, 60)
        if hours:
            remaining = f"{hours}小时{rest_minutes}分钟"
        else:
            remaining = f"{rest_minutes}分钟"

    due_text = assignment.due_at.astimezone().strftime("%Y-%m-%d %H:%M")
    return (
        f"学习通作业提醒 [{decision.tier.value.upper()}]\n"
        f"课程：{assignment.course}\n"
        f"作业：{assignment.title}\n"
        f"截止：{due_text}\n"
        f"剩余：{remaining}\n"
        f"原因：{decision.reason}"
    )

