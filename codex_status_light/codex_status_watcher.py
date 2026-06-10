import argparse
import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path

RESPONSE_KIND_RE = re.compile(r"event\.kind=(response\.[A-Za-z0-9_.-]+)")


def now_seconds() -> int:
    return int(time.time())


def norm_path(value: str) -> str:
    value = value.replace("\\\\?\\", "")
    return value.rstrip("\\/").lower()


def append_log(path: Path, message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {message}\n")


def connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)


def current_thread(state_db: Path, workspace: str) -> tuple[str | None, Path | None, int]:
    workspace_norm = norm_path(workspace)
    with connect_readonly(state_db) as con:
        rows = con.execute(
            """
            select id, cwd, updated_at_ms, source, rollout_path
            from threads
            where archived = 0
            order by updated_at_ms desc
            limit 20
            """
        ).fetchall()

    for thread_id, cwd, updated_at_ms, source, rollout_path in rows:
        if source not in ("vscode", "desktop", "app"):
            continue
        if norm_path(cwd) == workspace_norm:
            return thread_id, Path(rollout_path.replace("\\\\?\\", "")), int(updated_at_ms or 0)

    for thread_id, cwd, updated_at_ms, _source, rollout_path in rows:
        if norm_path(cwd) == workspace_norm:
            return thread_id, Path(rollout_path.replace("\\\\?\\", "")), int(updated_at_ms or 0)

    return None, None, 0


def latest_thread_activity(logs_db: Path, thread_id: str) -> int:
    with connect_readonly(logs_db) as con:
        row = con.execute(
            """
            select max(ts)
            from logs
            where thread_id = ?
            """,
            (thread_id,),
        ).fetchone()

    return int(row[0] or 0)


def latest_response_kind(logs_db: Path, thread_id: str) -> tuple[str | None, int]:
    with connect_readonly(logs_db) as con:
        rows = con.execute(
            """
            select ts, feedback_log_body
            from logs
            where feedback_log_body like ?
              and feedback_log_body like '%event.kind=response.%'
            order by id desc
            limit 120
            """,
            (f"%conversation.id={thread_id}%",),
        ).fetchall()

    for ts, body in rows:
        match = RESPONSE_KIND_RE.search(body or "")
        if match:
            return match.group(1), int(ts or 0)

    return None, 0


def tail_lines(path: Path, max_bytes: int = 2_000_000) -> list[str]:
    if not path.exists():
        return []

    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes), 0)
        data = f.read()

    text = data.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    if data and max_bytes < path.stat().st_size and lines:
        lines = lines[1:]
    return lines


def rollout_state(rollout_path: Path | None) -> tuple[str | None, bool, bool, str | None]:
    if not rollout_path:
        return None, False, False, None

    task_event = None
    pending_tools: dict[str, str] = {}
    pending_permissions: dict[str, str] = {}
    for line in tail_lines(rollout_path):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue

        payload_type = payload.get("type")
        if item.get("type") == "event_msg" and payload_type in ("task_started", "task_complete"):
            task_event = str(payload_type)
            pending_tools.clear()
            pending_permissions.clear()
            continue

        call_id = payload.get("call_id")
        if payload_type == "function_call" and call_id:
            args = payload.get("arguments") or ""
            tool_name = str(payload.get("name") or "tool")
            pending_tools[str(call_id)] = tool_name
            if "require_escalated" in args or "request_plugin_install" in args:
                pending_permissions[str(call_id)] = tool_name
        elif payload_type == "function_call_output" and call_id:
            pending_tools.pop(str(call_id), None)
            pending_permissions.pop(str(call_id), None)

    if pending_permissions:
        call_id = next(reversed(pending_permissions))
        return task_event, True, True, pending_permissions[call_id]

    if pending_tools:
        call_id = next(reversed(pending_tools))
        return task_event, False, True, pending_tools[call_id]

    return task_event, False, False, None


def choose_state(
    response_kind: str | None,
    response_ts: int,
    latest_activity_ts: int,
    thread_updated_at_ms: int,
    task_event: str | None,
    has_pending_permission: bool,
    has_pending_tool: bool,
    last_sent: str | None,
    stale_working_window: int,
    done_delay: int,
) -> str:
    if has_pending_permission:
        return "waiting"

    if has_pending_tool:
        return "working"

    if task_event == "task_complete":
        return "done"

    if task_event == "task_started":
        return "working"

    if response_kind == "response.completed":
        if last_sent in ("working", "waiting") and response_ts and now_seconds() - response_ts < done_delay:
            return "working"
        return "done"

    if response_kind and response_kind.startswith("response."):
        return "working"

    latest_ts = max(response_ts, latest_activity_ts, thread_updated_at_ms // 1000)
    if last_sent == "working" and latest_ts and now_seconds() - latest_ts <= stale_working_window:
        return "working"

    return "done"


def send_state(script: Path, state: str, port: str) -> None:
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-State",
            state,
            "-Port",
            port,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=r"F:\Codex_project")
    parser.add_argument("--port", default="COM6")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--stale-working-window", type=int, default=120)
    parser.add_argument("--done-delay", type=int, default=15)
    parser.add_argument("--codex-home", default=str(Path.home() / ".codex"))
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    bridge = base / "codex_light_bridge.ps1"
    log = base / "codex_status_watcher.log"
    state_db = Path(args.codex_home) / "state_5.sqlite"
    logs_db = Path(args.codex_home) / "logs_2.sqlite"

    append_log(log, f"watcher started workspace={args.workspace} port={args.port}")
    last_sent = None
    last_thread = None

    while True:
        try:
            thread_id, rollout_path, thread_updated_at_ms = current_thread(state_db, args.workspace)
            if not thread_id:
                state = "done"
            else:
                response_kind, response_ts = latest_response_kind(logs_db, thread_id)
                latest_activity_ts = latest_thread_activity(logs_db, thread_id)
                task_event, has_pending_permission, has_pending_tool, pending_name = rollout_state(rollout_path)
                state = choose_state(
                    response_kind,
                    response_ts,
                    latest_activity_ts,
                    thread_updated_at_ms,
                    task_event,
                    has_pending_permission,
                    has_pending_tool,
                    last_sent,
                    args.stale_working_window,
                    args.done_delay,
                )
                if thread_id != last_thread:
                    append_log(log, f"selected thread={thread_id} rollout={rollout_path}")
                    last_thread = thread_id
                if has_pending_permission and state != last_sent:
                    append_log(log, f"pending permission tool={pending_name}")
                elif has_pending_tool and state != last_sent:
                    append_log(log, f"pending tool={pending_name}")

            if state != last_sent:
                send_state(bridge, state, args.port)
                detail = ""
                if thread_id:
                    detail = f" task={task_event} response={response_kind}"
                append_log(log, f"sent state={state}{detail}")
                last_sent = state
        except Exception as exc:
            append_log(log, f"error {type(exc).__name__}: {exc}")

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
