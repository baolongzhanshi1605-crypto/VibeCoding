from __future__ import annotations

import math
import time
from typing import Any

from .models import QuotaWindow, TaskSnapshot


DEFAULT_PRIORITY = 3


class BudgetPlanner:
    def __init__(
        self,
        short_reserve_percent: float = 10.0,
        weekly_reserve_percent: float = 15.0,
        per_task_cap_percent: float = 40.0,
    ) -> None:
        self.short_reserve_percent = short_reserve_percent
        self.weekly_reserve_percent = weekly_reserve_percent
        self.per_task_cap_percent = per_task_cap_percent

    def plan_tokens(
        self, tasks: list[TaskSnapshot], windows: list[QuotaWindow],
        preferences: dict[str, dict[str, Any]], burn_rates: dict[str, float],
        used_tokens: dict[str, int], estimates: dict[str, dict[str, Any]],
        *, window: QuotaWindow | None, now: int, unreported_tokens: int = 0,
        weekly_window: QuotaWindow | None = None,
    ) -> dict[str, Any]:
        candidates = [task for task in tasks if task.status in {"running", "waiting"}]
        short = next((item for item in windows if item.kind == "short"), None)
        weekly = next((item for item in windows if item.kind == "weekly"), None)
        short_ratio = estimates.get("short", {}).get("tokens_per_percent")
        weekly_ratio = estimates.get("weekly", {}).get("tokens_per_percent")
        ratios = {"short": short_ratio, "weekly": weekly_ratio}
        for kind, ratio in ratios.items():
            ratios[kind] = float(ratio) if ratio and math.isfinite(float(ratio)) and ratio > 0 else None
        short_ratio, weekly_ratio = ratios["short"], ratios["weekly"]
        resets_at = window.resets_at if window else None
        valid_period = bool(resets_at and resets_at > now)
        available: int | None = None
        state = "awaiting_quota" if window else "unavailable"
        weekly_pending = weekly_window is not None and weekly_window not in windows
        if short and valid_period and not weekly_pending:
            short_points = max(0.0, short.remaining_percent - self.short_reserve_percent)
            weekly_points = max(0.0, weekly.remaining_percent - self.weekly_reserve_percent) if weekly else None
            if short_points == 0 or weekly_points == 0:
                available, state = 0, "ready"
            elif short_ratio and (not weekly or weekly_ratio):
                pools = [short_points * short_ratio]
                if weekly:
                    slots = max(1, math.ceil(max(0, (weekly.resets_at or now) - now) / 18000))
                    pools.append(weekly_points * weekly_ratio / slots)
                available = max(0, math.floor(min(pools) - max(0, unreported_tokens)))
                state = "ready"
            else:
                state = "calibrating"

        rates = {task.id: float(burn_rates.get(task.id) or 0) for task in candidates}
        rates = {key: rate if math.isfinite(rate) and rate > 0 else 0 for key, rate in rates.items()}
        known = sorted(rate for rate in rates.values() if rate > 0)
        baseline = known[len(known) // 2] if known else 0
        scores = {
            task.id: int(preferences.get(task.id, {}).get("priority", DEFAULT_PRIORITY)) /
            (math.sqrt(max(0.25, rates[task.id] / baseline)) if baseline and rates[task.id] else 1)
            for task in candidates
        }
        cap = short_ratio * self.per_task_cap_percent if short_ratio else 0
        manual = {
            task.id: min(cap, max(0, float(preferences[task.id]["manual_cap_percent"])) * short_ratio)
            for task in candidates
            if short_ratio and preferences.get(task.id, {}).get("manual_cap_percent") is not None
        }
        total_manual = sum(manual.values())
        scale = min(1, available / total_manual) if available is not None and total_manual else 1
        shares = {key: value * scale for key, value in manual.items()}
        remaining = max(0, (available or 0) - sum(shares.values()))
        score_total = sum(value for key, value in scores.items() if key not in manual) or 1
        allocations: dict[str, dict[str, Any]] = {}
        for task in candidates:
            value = math.floor(shares.get(task.id, min(cap, remaining * scores[task.id] / score_total))) if available is not None else None
            used = used_tokens.get(task.id) if valid_period else None
            rate = rates[task.id]
            seconds = None
            forecast = state
            if value is not None:
                if value == 0:
                    forecast, seconds = "exhausted", 0
                elif task.status == "waiting":
                    forecast = "waiting"
                elif rate == 0:
                    forecast = "unknown_rate"
                else:
                    projected = math.ceil(value / rate * 60)
                    if now + projected >= resets_at:
                        forecast = "after_reset"
                    else:
                        forecast, seconds = "exhausts", projected
            allocations[task.id] = {
                "window_used_tokens": used, "remaining_tokens": value,
                "suggested_total_tokens": used + value if used is not None and value is not None else None,
                "burn_rate_tokens_per_minute": round(rate, 1) if rate else None,
                "forecast": forecast, "seconds_remaining": seconds,
                "exhausts_at": now + seconds if seconds is not None else None,
                "mode": "manual_adjusted" if task.id in manual and scale < 1 else "manual" if task.id in manual else "automatic",
            }
        return {
            "state": state, "is_estimate": True, "advisory_only": True,
            "source": "local-quota-token-calibration", "active_tasks": len(candidates),
            "started_at": resets_at - window.window_minutes * 60 if valid_period else None,
            "resets_at": resets_at, "available_tokens": available,
            "unreported_tokens": max(0, unreported_tokens),
            "calibrations": estimates, "allocations": allocations,
        }

    def plan(
        self,
        tasks: list[TaskSnapshot],
        windows: list[QuotaWindow],
        preferences: dict[str, dict[str, Any]],
        burn_rates: dict[str, float],
        now: int | None = None,
    ) -> dict[str, Any]:
        now = now or int(time.time())
        candidates = [task for task in tasks if task.status in {"running", "waiting"}]
        short = next((window for window in windows if window.kind == "short"), None)
        weekly = next((window for window in windows if window.kind == "weekly"), None)

        short_pool = None
        if short:
            short_pool = max(0.0, short.remaining_percent - self.short_reserve_percent)

        weekly_pool = None
        weekly_slots = None
        if weekly:
            remaining = max(0.0, weekly.remaining_percent - self.weekly_reserve_percent)
            seconds_left = max(0, (weekly.resets_at or now) - now)
            weekly_slots = max(1, math.ceil(seconds_left / (5 * 3600)))
            weekly_pool = remaining / weekly_slots

        pools = [pool for pool in (short_pool, weekly_pool) if pool is not None]
        available = min(pools) if pools else 0.0
        source = "short_and_weekly" if len(pools) == 2 else "short" if short_pool is not None else "weekly_ration" if weekly_pool is not None else "unavailable"

        allocations: dict[str, dict[str, Any]] = {}
        if not candidates or available <= 0:
            return {
                "available_percent": round(available, 2),
                "source": source,
                "weekly_slots_remaining": weekly_slots,
                "allocations": allocations,
            }

        known_rates = [rate for rate in burn_rates.values() if rate > 0]
        baseline_rate = sorted(known_rates)[len(known_rates) // 2] if known_rates else None
        scores: dict[str, float] = {}
        for task in candidates:
            pref = preferences.get(task.id, {})
            priority = int(pref.get("priority", DEFAULT_PRIORITY))
            rate = burn_rates.get(task.id)
            burn_factor = 1.0
            if rate and baseline_rate:
                burn_factor = math.sqrt(max(0.25, rate / baseline_rate))
            scores[task.id] = priority / burn_factor

        total_score = sum(scores.values()) or 1.0
        automatic_suggestions = {
            task.id: min(self.per_task_cap_percent, available * scores[task.id] / total_score)
            for task in candidates
        }
        manual_targets: dict[str, float] = {}
        automatic_tasks: list[TaskSnapshot] = []
        for task in candidates:
            manual = preferences.get(task.id, {}).get("manual_cap_percent")
            if manual is None:
                automatic_tasks.append(task)
            else:
                manual_targets[task.id] = min(self.per_task_cap_percent, max(0.0, float(manual)))

        manual_total = sum(manual_targets.values())
        manual_scale = min(1.0, available / manual_total) if manual_total > 0 else 1.0
        manual_allocations = {
            task_id: target * manual_scale for task_id, target in manual_targets.items()
        }
        remaining = max(0.0, available - sum(manual_allocations.values()))
        automatic_score_total = sum(scores[task.id] for task in automatic_tasks) or 1.0

        for task in candidates:
            pref = preferences.get(task.id, {})
            manual = pref.get("manual_cap_percent")
            if manual is not None:
                cap = manual_allocations[task.id]
            else:
                cap = min(
                    self.per_task_cap_percent,
                    remaining * scores[task.id] / automatic_score_total,
                )
            rate = burn_rates.get(task.id)
            allocations[task.id] = {
                "cap_percent": round(max(0.0, cap), 2),
                "automatic_percent": round(max(0.0, automatic_suggestions[task.id]), 2),
                "manual_percent": round(float(manual), 2) if manual is not None else None,
                "priority": int(pref.get("priority", DEFAULT_PRIORITY)),
                "managed": bool(pref.get("managed", False)),
                "mode": "manual_adjusted" if manual is not None and manual_scale < 1 else "manual" if manual is not None else "automatic",
                "calibration": "ready" if rate else "collecting",
                "burn_rate_tokens_per_minute": round(rate, 1) if rate else None,
            }

        return {
            "available_percent": round(available, 2),
            "source": source,
            "weekly_slots_remaining": weekly_slots,
            "reserves": {
                "short_percent": self.short_reserve_percent,
                "weekly_percent": self.weekly_reserve_percent,
            },
            "allocations": allocations,
        }
