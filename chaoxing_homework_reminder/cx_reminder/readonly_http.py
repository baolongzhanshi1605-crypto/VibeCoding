from __future__ import annotations

from collections.abc import Mapping
import urllib.request


class ReadOnlyHttpClient:
    allowed_methods = {"GET", "HEAD"}

    def __init__(self, opener=None, timeout: int = 15) -> None:
        self.opener = opener or urllib.request.build_opener()
        self.timeout = timeout

    def get(self, url: str, headers: Mapping[str, str] | None = None):
        return self.request("GET", url, headers=headers)

    def head(self, url: str, headers: Mapping[str, str] | None = None):
        return self.request("HEAD", url, headers=headers)

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
    ):
        normalized = method.upper()
        if normalized not in self.allowed_methods:
            raise ValueError(f"Blocked non-read-only HTTP method: {normalized}")

        request = urllib.request.Request(
            url,
            headers=dict(headers or {}),
            method=normalized,
        )
        return self.opener.open(request, timeout=self.timeout)
