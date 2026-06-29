import json
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Backend: prefer curl_cffi because it impersonates a real browser's TLS
# fingerprint, which is what bypasses Cloudflare's 403 here. We fall back to
# `requests` if curl_cffi isn't installed so the script still runs.
# ---------------------------------------------------------------------------
try:
    from curl_cffi import requests as cf_requests  # type: ignore

    _HAS_CFFI = True
except ImportError:  # pragma: no cover
    import requests as cf_requests  # type: ignore

    _HAS_CFFI = False

# ---------------------------------------------------------------------------
# Hardcoded capture values — kept in sync with the original browser request
# seen in the network panel. Tweak these directly to retarget a different
# chapter without re-reading any JSON file.
# ---------------------------------------------------------------------------

# Outer URL the browser hits
GATEWAY_URL = "https://fictionzone.net/api/__api_party/fictionzone"

# Outer HTTP headers sent by the browser.
OUTER_HEADERS = {
    "accept": "application/json",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "content-type": "application/json",
    "origin": "https://fictionzone.net",
    "priority": "u=1, i",
    "referer": "https://fictionzone.net/novel/the-destiny-s-ultimate-villain-starting-from-killing-the-protagonist/1806738",
    "sec-ch-ua": "\"Google Chrome\";v=\"149\", \"Chromium\";v=\"149\", \"Not)A;Brand\";v=\"24\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
}

# Bearer token used inside the inner headers array
AUTH_TOKEN = (
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJ1c2VyX2lkIjoiMjU4NDA2NTQ4Mzg3MTM1NjIwIiwidXNlcm5hbWUiOiJzaGFocmlhcnNlYW0xNyIsImVtYWlsIjoic2hhaHJpYXJzZWFtMTdAZ21haWwuY29tIiwidG9rZW5fdHlwZSI6ImFjY2VzcyIsImlzcyI6InVzZXItc2VydmljZSIsInN1YiI6IjI1ODQwNjU0ODM4NzEzNTYyMCIsImV4cCI6MTc4NDk1ODE1NiwibmJmIjoxNzgyMzY2MTU2LCJpYXQiOjE3ODIzNjYxNTYsImp0aSI6IjRiZDk4OGJmYWY3MDA0Y2Y4MjJhZGJkMDAzYTcxMmE0In0."
    "MZA-8RzaPp4GELWXtRgTCFYnnihOGk2yKIe_Pj8yNYQ"
)

# Default target chapter
DEFAULT_NOVEL_ID = "27413"
DEFAULT_CHAPTER_ID = "1806738"


def build_inner_payload(novel_id: str, chapter_id: str, highlight: bool = True) -> dict:
    """Build the inner routing instruction that gets posted as the body."""
    current_time = datetime.now(timezone.utc)
    now_iso = current_time.strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{current_time.microsecond // 1000:03d}Z"

    return {
        "path": "/platform/chapter-content",
        "method": "GET",
        "query": {
            "novel_id": str(novel_id),
            "chapter_id": str(chapter_id),
            "highlight": bool(highlight),
        },
        "headers": [
            ["authorization", AUTH_TOKEN],
            ["x-request-time", now_iso],
        ],
    }


def _print_http_error(response) -> None:
    """Show enough context for a 4xx/5xx to diagnose Cloudflare vs auth."""
    print(f"[HTTP {response.status_code}] {response.reason} for url: {response.url}")
    cf_ray = response.headers.get("cf-ray")
    if cf_ray:
        print(f"  Cloudflare ray: {cf_ray}")
    server = response.headers.get("server")
    if server:
        print(f"  Server: {server}")

    body = response.text or ""
    if body:
        snippet = body if len(body) <= 400 else body[:400] + "...(truncated)"
        print(f"  Body: {snippet}")


def fetch_chapter(novel_id: str = DEFAULT_NOVEL_ID,
                  chapter_id: str = DEFAULT_CHAPTER_ID,
                  highlight: bool = True,
                  timeout: int = 10) -> dict:
    """POST the inner routing instruction to the gateway and return the response."""
    inner = build_inner_payload(novel_id, chapter_id, highlight)

    backend = "curl_cffi (Chrome 120 impersonation)" if _HAS_CFFI else "requests (no TLS impersonation)"
    print(f"Sending request to gateway: {GATEWAY_URL}")
    print(f"HTTP backend: {backend}")
    print("Inner payload:")
    print(json.dumps(inner, indent=2))

    post_kwargs = {
        "headers": OUTER_HEADERS,
        "json": inner,
        "timeout": timeout,
    }
    # curl_cffi supports `impersonate` to mimic a real browser's TLS fingerprint.
    if _HAS_CFFI:
        post_kwargs["impersonate"] = "chrome120"

    try:
        response = cf_requests.post(GATEWAY_URL, **post_kwargs)
    except Exception as err:  # noqa: BLE001 - surface any transport error
        print(f"Request error: {err}")
        raise

    if response.status_code >= 400:
        _print_http_error(response)
        if response.status_code == 403:
            print(
                "\n403 diagnosis:\n"
                "  - If `cf-ray` is present in the headers, Cloudflare is rejecting\n"
                "    the TLS fingerprint (JA3/JA4). Install `curl_cffi` and rerun.\n"
                "  - If `cf-ray` is absent, the auth token is invalid or expired."
            )
        # Don't raise — return a structured dict so the caller can inspect it.
        return {
            "success": False,
            "status_code": response.status_code,
            "reason": response.reason,
            "headers": dict(response.headers),
            "body": response.text,
        }

    try:
        server_response = response.json()
    except ValueError:
        print("[Error] Response was not valid JSON.")
        print(response.text[:400])
        return {
            "success": False,
            "status_code": response.status_code,
            "reason": response.reason,
            "body": response.text,
        }

    print("\n[Success] Response Received:")
    print(json.dumps(server_response, indent=2))

    if server_response.get("success"):
        data = server_response.get("data", {}) or {}
        title = data.get("title", "No Title Found")
        content = data.get("content", "No Content Found")
        print(f"\nExtracted Title: {title}")
        print(f"Content Preview: {content[:120]}...")

    return server_response


if __name__ == "__main__":
    result = fetch_chapter()
    if isinstance(result, dict) and not result.get("success"):
        sys.exit(1)