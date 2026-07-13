from __future__ import annotations

import argparse
import json
import mimetypes
import signal
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from codex_monitor import MonitorService


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
RUNTIME_ROOT = PROJECT_ROOT / "runtime"


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], service: MonitorService) -> None:
        super().__init__(address, DashboardHandler)
        self.service = service


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "CodexQuotaManager/0.1"

    @property
    def dashboard(self) -> DashboardServer:
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(self.dashboard.service.snapshot())
            return
        if path == "/health":
            snapshot = self.dashboard.service.snapshot()
            self._json({"status": snapshot.get("health", "unknown")})
            return
        if path in {"/", "/display"}:
            self._file(WEB_ROOT / "index.html", no_cache=True)
            return
        relative = unquote(path.lstrip("/"))
        target = (WEB_ROOT / relative).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._file(target, no_cache=True)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        prefix = "/api/tasks/"
        if not path.startswith(prefix) or not path.endswith("/settings"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        task_id = unquote(path[len(prefix) : -len("/settings")]).strip("/")
        if not task_id or len(task_id) > 100:
            self._json({"error": "invalid task id"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            result = self.dashboard.service.update_task(task_id, payload)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._json({"task_id": task_id, "preference": result})

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, no_cache: bool = False) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type in {"application/javascript", "application/manifest+json"} else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if no_cache else "public, max-age=300")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'",
        )

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write(f"{self.address_string()} - {fmt % args}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Codex token and quota dashboard")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--codex-home", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = MonitorService(RUNTIME_ROOT, codex_home=args.codex_home, poll_seconds=args.poll)
    service.start()
    server = DashboardServer((args.host, args.port), service)

    def stop_server(_signum: int, _frame: object) -> None:
        server.shutdown()

    signal.signal(signal.SIGINT, stop_server)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_server)

    print(f"Codex Quota Manager listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
