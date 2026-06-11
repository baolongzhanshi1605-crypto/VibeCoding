from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .models import Assignment
from .notifiers.messages import format_reminder_message
from .policy import ReminderPolicy
from .state import ReminderState


class AssignmentProvider(Protocol):
    def fetch_assignments(self) -> list[Assignment]:
        ...


class Notifier(Protocol):
    def send(self, title: str, content: str) -> bool:
        ...


@dataclass(frozen=True)
class CheckResult:
    checked: int
    notified: int
    skipped: int


def run_check(
    provider: AssignmentProvider,
    state: ReminderState,
    policy: ReminderPolicy,
    notifiers: list[Notifier],
    now: datetime,
    trigger: str,
) -> CheckResult:
    assignments = provider.fetch_assignments()
    notified = 0
    skipped = 0

    for assignment in assignments:
        decision = policy.decide(assignment, now)
        if not state.should_send(decision, now, trigger):
            skipped += 1
            continue

        title = f"Chaoxing Homework Reminder: {assignment.course}"
        content = format_reminder_message(decision, now)
        delivered = False
        for notifier in notifiers:
            delivered = notifier.send(title, content) or delivered

        if delivered:
            state.mark_sent(decision, now)
            notified += 1
        else:
            skipped += 1

    return CheckResult(checked=len(assignments), notified=notified, skipped=skipped)
