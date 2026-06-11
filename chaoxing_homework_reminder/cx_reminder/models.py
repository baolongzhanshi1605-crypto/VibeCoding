from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    course: str
    title: str
    due_at: datetime
    submitted: bool


class Trigger(str, Enum):
    LOGIN = "login"
    UNLOCK = "unlock"
    WAKE = "wake"
    TIMER = "timer"
    MANUAL = "manual"


@dataclass(frozen=True)
class ReminderDecision:
    assignment: Assignment
    tier: "ReminderTier"
    reason: str
