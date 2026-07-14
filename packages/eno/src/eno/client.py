"""Stdlib HTTP client for eno-service. Keeps the lib package httpx-free."""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class ClientError(Exception):
    pass


class EnoClient:
    def __init__(self, base_url: str, *, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            qs = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None},
                doseq=True,
            )
            url += "?" + qs
        req = urllib.request.Request(url, method="GET")
        return self._send(req)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST", headers={"Content-Type": "application/json"}
        )
        return self._send(req)

    def _send(self, req: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                detail = json.load(e)
            except Exception:
                detail = e.read().decode("utf-8", errors="replace")
            if e.code == 404:
                return None
            raise ClientError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ClientError(f"unreachable: {e.reason}") from e
