from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from .models import ReminderDecision
from .policy import ReminderTier


class ReminderState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def should_send(
        self,
        decision: ReminderDecision,
        now: datetime,
        trigger: str,
    ) -> bool:
        if decision.tier == ReminderTier.NONE:
            return False

        last_sent = self._last_sent_at(decision)
        if last_sent is None:
            return True

        elapsed = now - last_sent
        if decision.tier == ReminderTier.URGENT:
            return elapsed >= timedelta(minutes=15)
        if decision.tier == ReminderTier.STRONG:
            if trigger in {"login", "unlock", "manual"}:
                return elapsed >= timedelta(minutes=30)
            return elapsed >= timedelta(hours=4)
        if decision.tier in {ReminderTier.PREVIEW, ReminderTier.OVERDUE}:
            return last_sent.date() != now.date()
        return False

    def mark_sent(self, decision: ReminderDecision, now: datetime) -> None:
        key = self._key(decision)
        self.data.setdefault("sent", {})[key] = now.isoformat()
        self._save()

    def _last_sent_at(self, decision: ReminderDecision) -> datetime | None:
        value = self.data.get("sent", {}).get(self._key(decision))
        if not value:
            return None
        return datetime.fromisoformat(value)

    def _key(self, decision: ReminderDecision) -> str:
        assignment = decision.assignment
        due_key = assignment.due_at.isoformat()
        return f"{assignment.assignment_id}|{due_key}|{decision.tier.value}"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sent": {}}
        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)

