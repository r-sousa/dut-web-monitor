from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content_type: str
    text: str
    etag: str | None
    last_modified: str | None


class PoliteClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = requests.Session()
        retry = Retry(
            total=settings.max_retries,
            connect=settings.max_retries,
            read=settings.max_retries,
            status=settings.max_retries,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en,pt-PT;q=0.8,pt;q=0.7",
            }
        )
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.settings.delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def get(self, url: str, accepted_statuses: Iterable[int] = (200,)) -> FetchResult:
        self._throttle()
        response = self.session.get(url, timeout=self.settings.request_timeout_seconds)
        self._last_request_at = time.monotonic()
        if response.status_code not in set(accepted_statuses):
            response.raise_for_status()
        return FetchResult(
            url=response.url,
            status_code=response.status_code,
            content_type=response.headers.get("Content-Type", ""),
            text=response.text,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )
