from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from ..models import Assignment


class ManualJsonProvider:
    def __init__(self, path: Path) -> None:
        self.path = path

    def fetch_assignments(self) -> list[Assignment]:
        with self.path.open("r", encoding="utf-8") as file:
            rows = json.load(file)

        assignments = []
        for row in rows:
            assignments.append(
                Assignment(
                    assignment_id=str(row["assignment_id"]),
                    course=str(row["course"]),
                    title=str(row["title"]),
                    due_at=datetime.fromisoformat(str(row["due_at"])),
                    submitted=bool(row["submitted"]),
                )
            )
        return assignments

