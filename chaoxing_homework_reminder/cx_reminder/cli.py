from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .notifiers.console import ConsoleNotifier
from .notifiers.windows_popup import WindowsPopupNotifier
from .policy import ReminderPolicy
from .providers.manual_json import ManualJsonProvider
from .runner import run_check
from .state import ReminderState


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Chaoxing homework reminder")
    parser.add_argument("--config", default="config.json")
    parser.add_argument(
        "--trigger",
        choices=["login", "unlock", "timer", "manual"],
        default="manual",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    config = _load_config(config_path)
    timezone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    now = datetime.now(timezone)

    provider = ManualJsonProvider(Path(config["manual_assignments_path"]))
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


if __name__ == "__main__":
    raise SystemExit(main())
