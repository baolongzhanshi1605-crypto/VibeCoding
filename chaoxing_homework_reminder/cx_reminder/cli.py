from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .notifiers.console import ConsoleNotifier
from .notifiers.windows_popup import WindowsPopupNotifier
from .policy import ReminderPolicy
from .providers.chaoxing_readonly import ChaoxingReadOnlyProvider
from .providers.manual_json import ManualJsonProvider
from .runner import run_check
from .state import ReminderState


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Chaoxing homework reminder")
    parser.add_argument("--config", default="config.json")
    parser.add_argument(
        "--trigger",
        choices=["login", "unlock", "wake", "timer", "manual"],
        default="manual",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    config = _load_config(config_path)
    timezone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    now = datetime.now(timezone)

    provider = build_provider(config, timezone, now)
    state = ReminderState(Path(config.get("state_path", "data/state.json")))
    policy = ReminderPolicy(lookahead_hours=int(config.get("lookahead_hours", 36)))

    notifiers = build_notifiers(config)

    result = run_check(provider, state, policy, notifiers, now, args.trigger)
    print(
        f"checked={result.checked} notified={result.notified} skipped={result.skipped}"
    )
    return 0


def _load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_notifiers(config: dict) -> list:
    notifiers = [ConsoleNotifier()]
    if config.get("enable_windows_popup", False):
        notifiers.append(WindowsPopupNotifier())
    return notifiers


def build_provider(config: dict, timezone: ZoneInfo, now: datetime):
    provider_name = config.get("provider", "manual")
    if provider_name == "manual":
        return ManualJsonProvider(Path(config["manual_assignments_path"]))
    if provider_name == "chaoxing":
        return ChaoxingReadOnlyProvider(
            edge_profile_path=Path(config.get("edge_profile_path", "data/edge_profile")),
            course_cache_path=Path(
                config.get("course_cache_path", "data/course_cards_attrs.json")
            ),
            cache_dir=Path(config.get("chaoxing_cache_dir", "data")),
            timezone=timezone,
            current_year=now.year,
            request_delay_seconds=float(config.get("request_delay_seconds", 0.2)),
        )
    raise SystemExit(f"Unknown provider: {provider_name}")


if __name__ == "__main__":
    raise SystemExit(main())
