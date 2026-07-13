from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "TokenUsage":
        payload = payload or {}
        return cls(
            input_tokens=int(payload.get("input_tokens") or 0),
            cached_input_tokens=int(payload.get("cached_input_tokens") or 0),
            output_tokens=int(payload.get("output_tokens") or 0),
            reasoning_output_tokens=int(payload.get("reasoning_output_tokens") or 0),
            total_tokens=int(payload.get("total_tokens") or 0),
        )


@dataclass(frozen=True)
class QuotaWindow:
    limit_id: str
    window_minutes: int
    used_percent: float
    resets_at: int | None
    observed_at: int

    @property
    def remaining_percent(self) -> float:
        return max(0.0, 100.0 - self.used_percent)

    @property
    def kind(self) -> str:
        if 240 <= self.window_minutes <= 360:
            return "short"
        if 9_000 <= self.window_minutes <= 11_000:
            return "weekly"
        return "custom"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["remaining_percent"] = round(self.remaining_percent, 2)
        value["kind"] = self.kind
        return value


@dataclass
class TaskSnapshot:
    id: str
    title: str
    cwd: str
    source: str
    model: str | None
    reasoning_effort: str | None
    status: str
    updated_at: int
    tokens: TokenUsage
    rollout_path: str
    created_at: int | None = None
    last_event_at: int | None = None
    pending_tool: str | None = None
    turn_tokens: int = 0
    turn_started_at: int | None = None
    turn_finished_at: int | None = None
    preference: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    burn_rate_tokens_per_minute: float | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["title"] = self.title.strip() or "未命名任务"
        return value


@dataclass
class MonitorSnapshot:
    generated_at: int
    source: str
    health: str
    tasks: list[TaskSnapshot]
    quota_windows: list[QuotaWindow]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        active = sum(task.status in {"running", "waiting"} for task in self.tasks)
        waiting = sum(task.status == "waiting" for task in self.tasks)
        return {
            "generated_at": self.generated_at,
            "source": self.source,
            "health": self.health,
            "summary": {
                "active_tasks": active,
                "waiting_tasks": waiting,
                "visible_tasks": len(self.tasks),
            },
            "quota_windows": [window.to_dict() for window in self.quota_windows],
            "tasks": [task.to_dict() for task in self.tasks],
            "warnings": self.warnings,
        }
