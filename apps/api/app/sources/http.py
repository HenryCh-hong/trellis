"""Polite HTTP fetcher shared by every server-side adapter.

Deliberate constraints:
- identifies itself with a real UA and contact address,
- honours robots.txt when enabled,
- rate-limits per host,
- caps response size,
- never sends cookies or credentials, and is never pointed at a page behind
  someone's login (that path goes through the browser extension instead).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser

from app.core.config import get_settings


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int | None
    text: str | None
    html: str | None
    title: str | None
    error: str | None
    fetched_at: datetime
    content_type: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300


class PoliteFetcher:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._lock = threading.Lock()
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        ua = self._settings.user_agent
        if self._settings.fetch_contact_email:
            ua = ua.replace("set FETCH_CONTACT_EMAIL", self._settings.fetch_contact_email)
        self._ua = ua
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=self._settings.fetch_timeout_seconds,
            headers={
                "User-Agent": self._ua,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    # -- politeness ------------------------------------------------------
    def _throttle(self, host: str) -> None:
        delay = self._settings.polite_delay_seconds
        if delay <= 0:
            return
        with self._lock:
            last = self._last_hit.get(host, 0.0)
            wait = delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_hit[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        if not self._settings.respect_robots_txt:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                resp = self._client.get(f"{origin}/robots.txt", timeout=10.0)
                if resp.status_code < 400:
                    parser.parse(resp.text.splitlines())
                else:
                    parser = None
            except Exception:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        if parser is None:
            return True
        return parser.can_fetch(self._ua, url)

    # -- fetching --------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        now = datetime.now(UTC)
        if not self._allowed(url):
            return FetchResult(url, None, None, None, None, "blocked by robots.txt", now)
        self._throttle(urlparse(url).netloc)
        try:
            resp = self._client.get(url)
        except Exception as exc:
            return FetchResult(url, None, None, None, None, f"{type(exc).__name__}: {exc}", now)

        content_type = resp.headers.get("content-type", "")
        raw = resp.content[: self._settings.fetch_max_bytes]
        if resp.status_code >= 400:
            return FetchResult(
                url, resp.status_code, None, None, None, f"HTTP {resp.status_code}", now, content_type
            )
        if "application/json" in content_type:
            return FetchResult(
                url, resp.status_code, raw.decode("utf-8", "replace"), None, None, None, now, content_type
            )

        html = raw.decode(resp.encoding or "utf-8", "replace")
        title, text = html_to_text(html)
        return FetchResult(url, resp.status_code, text, html, title, None, now, content_type)

    def get_json(self, url: str) -> tuple[int | None, dict | list | None, str | None]:
        self._throttle(urlparse(url).netloc)
        try:
            resp = self._client.get(url, headers={"Accept": "application/json"})
            if resp.status_code >= 400:
                return resp.status_code, None, f"HTTP {resp.status_code}"
            return resp.status_code, resp.json(), None
        except Exception as exc:
            return None, None, f"{type(exc).__name__}: {exc}"

    def close(self) -> None:
        self._client.close()


def html_to_text(html: str) -> tuple[str | None, str]:
    """Extract a readable title + body text, dropping chrome and scripts."""
    tree = HTMLParser(html)
    for tag in ("script", "style", "noscript", "svg", "form", "iframe"):
        for node in tree.css(tag):
            node.decompose()
    title = tree.css_first("title")
    title_text = title.text(strip=True) if title else None

    body = tree.css_first("main") or tree.css_first("article") or tree.body
    if body is None:
        return title_text, ""
    text = body.text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines()]
    cleaned: list[str] = []
    seen_run = 0
    for ln in lines:
        if not ln:
            seen_run += 1
            if seen_run > 1:
                continue
        else:
            seen_run = 0
        cleaned.append(ln)
    return title_text, "\n".join(cleaned).strip()


_fetcher: PoliteFetcher | None = None


def get_fetcher() -> PoliteFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = PoliteFetcher()
    return _fetcher
