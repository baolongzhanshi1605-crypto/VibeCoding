from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from .models import Assignment, ReminderDecision


class ReminderTier(str, Enum):
    NONE = "none"
    PREVIEW = "preview"
    STRONG = "strong"
    URGENT = "urgent"
    OVERDUE = "overdue"


class ReminderPolicy:
    def __init__(
        self,
        lookahead_hours: int = 36,
        urgent_hours: int = 1,
        strong_hours: int = 6,
    ) -> None:
        self.lookahead = timedelta(hours=lookahead_hours)
        self.urgent = timedelta(hours=urgent_hours)
        self.strong = timedelta(hours=strong_hours)

    def decide(self, assignment: Assignment, now: datetime) -> ReminderDecision:
        if assignment.submitted:
            return ReminderDecision(assignment, ReminderTier.NONE, "already submitted")

        time_left = assignment.due_at - now
        if time_left.total_seconds() < 0:
            return ReminderDecision(assignment, ReminderTier.OVERDUE, "deadline passed")
        if time_left <= self.urgent:
            return ReminderDecision(assignment, ReminderTier.URGENT, "due within 1 hour")
        if time_left <= self.strong:
            return ReminderDecision(assignment, ReminderTier.STRONG, "due within 6 hours")
        if time_left <= self.lookahead:
            return ReminderDecision(
                assignment,
                ReminderTier.PREVIEW,
                "due within lookahead window",
            )
        return ReminderDecision(assignment, ReminderTier.NONE, "outside lookahead window")

