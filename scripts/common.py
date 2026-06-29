"""Shared config + helpers for the fictionzone downloader pipeline.

All other scripts (fetch_chapter, fetch_chapter_list, fetch_book_info,
scrape_novel, compile_epub) import from this module. Keep the constants
below in sync with the live site if any of the captured values change.
"""
from __future__ import annotations

import random
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# HTTP backend selection: curl_cffi impersonates Chrome's TLS fingerprint,
# which is what bypasses the Cloudflare 403 you get with plain `requests`.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - environment dependent
    from curl_cffi import requests as cf_requests  # type: ignore

    _HAS_CFFI = True
except ImportError:  # pragma: no cover
    import requests as cf_requests  # type: ignore

    _HAS_CFFI = False


def backend_name() -> str:
    return "curl_cffi" if _HAS_CFFI else "requests"


# ---------------------------------------------------------------------------
# Captured request values
# ---------------------------------------------------------------------------
GATEWAY_URL = "https://fictionzone.net/api/__api_party/fictionzone"
SITE_ORIGIN = "https://fictionzone.net"

AUTH_TOKEN = (
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJ1c2VyX2lkIjoiMjU4NDA2NTQ4Mzg3MTM1NjIwIiwidXNlcm5hbWUiOiJzaGFocmlhcnNlYW0xNyIsImVtYWlsIjoic2hhaHJpYXJzZWFtMTdAZ21haWwuY29tIiwidG9rZW5fdHlwZSI6ImFjY2VzcyIsImlzcyI6InVzZXItc2VydmljZSIsInN1YiI6IjI1ODQwNjU0ODM4NzEzNTYyMCIsImV4cCI6MTc4NDk1ODE1NiwibmJmIjoxNzgyMzY2MTU2LCJpYXQiOjE3ODIzNjYxNTYsImp0aSI6IjRiZDk4OGJmYWY3MDA0Y2Y4MjJhZGJkMDAzYTcxMmE0In0."
    "MZA-8RzaPp4GELWXtRgTCFYnnihOGk2yKIe_Pj8yNYQ"
)

# Browser headers. `accept-encoding` is restricted to gzip/deflate so the
# `requests` fallback path can still decode the body if curl_cffi is missing.
OUTER_HEADERS = {
    "accept": "application/json",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "content-type": "application/json",
    "origin": SITE_ORIGIN,
    "priority": "u=1, i",
    "referer": f"{SITE_ORIGIN}/",
    "sec-ch-ua": "\"Google Chrome\";v=\"149\", \"Chromium\";v=\"149\", \"Not)A;Brand\";v=\"24\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
}

# Headers used when fetching the public HTML page (book info).
HTML_HEADERS = {
    **OUTER_HEADERS,
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-encoding": "gzip, deflate, br, zstd",
}

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
BOOKS_ROOT = REPO_ROOT / "books"


def novel_dir(novel_id: str) -> Path:
    """Return (and create) books/{novelID}/."""
    path = BOOKS_ROOT / str(novel_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Time / filename helpers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    """ISO-8601 UTC timestamp with millisecond precision."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


_FILENAME_SAFE_RE = re.compile(r"[^\w\-. ]+", re.UNICODE)


def safe_filename(name: str, fallback: str = "untitled") -> str:
    """Return a filename safe for both Windows and POSIX filesystems."""
    if not name:
        return fallback
    # Normalize unicode and strip control chars
    cleaned = unicodedata.normalize("NFKC", name).strip()
    cleaned = "".join(ch for ch in cleaned if ch.isprintable() and ch not in "\r\n\t")
    cleaned = _FILENAME_SAFE_RE.sub("_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    if not cleaned or len(cleaned) > 200:
        return fallback
    return cleaned


def jitter_sleep(min_seconds: float, max_seconds: float) -> float:
    """Sleep for a random duration and return the actual seconds slept."""
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)
    return delay


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------
def build_inner_payload(path: str, query: Optional[dict] = None) -> dict:
    """Build the inner routing instruction that goes in the POST body."""
    headers = [
        ["authorization", AUTH_TOKEN],
        ["x-request-time", now_iso()],
    ]
    return {
        "path": path,
        "method": "GET",
        "query": query or {},
        "headers": headers,
    }


def _post_kwargs(json_body: dict, timeout: int) -> dict:
    kwargs: dict[str, Any] = {
        "headers": OUTER_HEADERS,
        "json": json_body,
        "timeout": timeout,
    }
    if _HAS_CFFI:
        kwargs["impersonate"] = "chrome120"
    return kwargs


def post_gateway(path: str, query: Optional[dict] = None, timeout: int = 15) -> dict:
    """POST the inner routing instruction and return the parsed JSON response.

    Raises `requests.exceptions.HTTPError` on >=400, `requests.RequestException`
    on transport errors, and `ValueError` when the body isn't valid JSON.
    """
    inner = build_inner_payload(path, query)
    response = cf_requests.post(GATEWAY_URL, **_post_kwargs(inner, timeout=timeout))
    response.raise_for_status()
    return response.json()


def post_gateway_safe(path: str, query: Optional[dict] = None,
                      timeout: int = 15) -> dict:
    """Like `post_gateway` but never raises — returns a structured dict instead."""
    inner = build_inner_payload(path, query)
    try:
        response = cf_requests.post(GATEWAY_URL, **_post_kwargs(inner, timeout=timeout))
    except Exception as err:  # noqa: BLE001
        return {"success": False, "error": f"transport: {err}"}

    if response.status_code >= 400:
        return {
            "success": False,
            "status_code": response.status_code,
            "reason": response.reason,
            "cf_ray": response.headers.get("cf-ray"),
            "body_snippet": (response.text or "")[:400],
        }
    try:
        return response.json()
    except ValueError:
        return {
            "success": False,
            "status_code": response.status_code,
            "error": "invalid JSON",
            "body_snippet": (response.text or "")[:400],
        }


def get_html(url: str, timeout: int = 20) -> str:
    """GET a page with browser-like TLS and return the decoded text body."""
    kwargs: dict[str, Any] = {"headers": HTML_HEADERS, "timeout": timeout}
    if _HAS_CFFI:
        kwargs["impersonate"] = "chrome120"
    response = cf_requests.get(url, **kwargs)
    response.raise_for_status()
    # curl_cffi / requests auto-decode gzip/deflate
    return response.text


def get_bytes(url: str, timeout: int = 20) -> bytes:
    """GET a binary resource (e.g. cover image) and return raw bytes."""
    kwargs: dict[str, Any] = {"headers": HTML_HEADERS, "timeout": timeout}
    if _HAS_CFFI:
        kwargs["impersonate"] = "chrome120"
    response = cf_requests.get(url, **kwargs)
    response.raise_for_status()
    return response.content


# ---------------------------------------------------------------------------
# Entry-point guard for direct execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"HTTP backend: {backend_name()}")
    print(f"Books root:   {BOOKS_ROOT}")
    print(f"Gateway URL:  {GATEWAY_URL}")
    sys.exit(0)
