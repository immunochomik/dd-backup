"""Small Datadog API client for dashboard reads."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class DatadogError(RuntimeError):
    pass


class DatadogClient:
    def __init__(self, site: str, api_key: str, app_key: str, timeout_seconds: float = 20):
        self.base_url = f"https://api.{site}"
        self.headers = {
            "Accept": "application/json",
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
        }
        self.timeout_seconds = timeout_seconds

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        if params:
            url += "?" + urlencode(params)
        request = Request(url, headers=self.headers)
        for attempt in range(4):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.load(response)
            except HTTPError as error:
                retryable = error.code in (429, 500, 502, 503, 504)
                if retryable and attempt < 3:
                    retry_after = error.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.isdigit() else 2**attempt
                    time.sleep(min(delay, 30))
                    continue
                detail = error.read().decode("utf-8", errors="replace")[:300]
                raise DatadogError(f"Datadog GET {path} failed (HTTP {error.code}): {detail}") from error
            except URLError as error:
                if attempt < 3:
                    time.sleep(2**attempt)
                    continue
                raise DatadogError(f"Datadog GET {path} failed: {error.reason}") from error
        raise AssertionError("retry loop should return or raise")

    def list_dashboards(self, page_size: int = 100) -> list[dict[str, Any]]:
        dashboards: list[dict[str, Any]] = []
        seen: set[str] = set()
        start = 0
        while True:
            response = self._get("/api/v1/dashboard", {"count": page_size, "start": start})
            page = response.get("dashboards")
            if not isinstance(page, list):
                raise DatadogError("Dashboard list response has no dashboards array")
            new_on_page = 0
            for item in page:
                dashboard_id = str(item.get("id", ""))
                if not dashboard_id:
                    raise DatadogError("Dashboard list contains an item without an ID")
                if dashboard_id not in seen:
                    seen.add(dashboard_id)
                    dashboards.append(item)
                    new_on_page += 1
            if page and not new_on_page:
                raise DatadogError("Dashboard pagination repeated a page")
            if len(page) < page_size:
                return dashboards
            start += page_size

    def get_dashboard(self, dashboard_id: str) -> dict[str, Any]:
        return self._get("/api/v1/dashboard/" + quote(dashboard_id, safe=""))

    def get_powerpack(self, powerpack_id: str) -> dict[str, Any]:
        return self._get("/api/v2/powerpacks/" + quote(powerpack_id, safe=""))
