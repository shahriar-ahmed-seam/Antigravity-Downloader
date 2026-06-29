"""
FictionZone API - Chapter Content Diagnostic Tool (v2)
Tests cookie-in-outer-headers to verify full authenticated content delivery.
"""
import json
import time
from datetime import datetime, timezone
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

try:
    from curl_cffi import requests as cf_requests
    HAS_CFFI = True
except ImportError:
    import requests as cf_requests
    HAS_CFFI = False

from backend.config import GATEWAY_URL, OUTER_HEADERS, SITE_ORIGIN

def now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

results = []

def test_request(name: str, outer_headers: dict, inner_payload: dict):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    kwargs = {
        "headers": outer_headers,
        "json": inner_payload,
        "timeout": 20
    }
    if HAS_CFFI:
        kwargs["impersonate"] = "chrome120"

    start_time = time.time()
    try:
        response = cf_requests.post(GATEWAY_URL, **kwargs)
        elapsed = time.time() - start_time
        print(f"  Status: {response.status_code} ({elapsed:.2f}s)")
        
        if response.status_code != 200:
            print(f"  Error: {response.text[:300]}")
            results.append((name, "FAIL", response.status_code, 0))
            return
            
        data = response.json()
        if not data.get("success"):
            msg = data.get("error") or data.get("message") or "Unknown"
            print(f"  API Error: {msg}")
            results.append((name, "API_ERROR", 200, 0))
            return
            
        chapter_data = data.get("data", {}) or {}
        content = chapter_data.get("content", "")
        content_len = len(content)
        
        print(f"  Content Length: {content_len} characters")
        print(f"  Title: {chapter_data.get('title', 'N/A')}")
        
        if content_len > 0:
            print(f"  First 100: {content[:100].strip()}")
            print(f"  Last  100: {content[-100:].strip()}")
        
        results.append((name, "OK", 200, content_len))
            
    except Exception as e:
        print(f"  Exception: {e}")
        results.append((name, "EXCEPTION", 0, 0))

def main():
    print("FictionZone Chapter Content Diagnostic v2")
    print(f"Backend: {'curl_cffi' if HAS_CFFI else 'requests'}")
    print("-" * 60)
    
    novel_id = input("Novel ID [71679]: ").strip() or "71679"
    chapter_id = input("Chapter ID [6410897]: ").strip() or "6410897"
    token = input("Auth Token: ").strip()
    cookie = input("Full Cookie string from browser: ").strip()
    
    if not token:
        print("Token required!")
        return

    if token and not token.startswith("Bearer "):
        token = f"Bearer {token}"

    query = {"novel_id": novel_id, "chapter_id": chapter_id, "highlight": False}
    
    inner = {
        "path": "/platform/chapter-content",
        "method": "GET",
        "query": query,
        "headers": [
            ["authorization", token],
            ["x-request-time", now_iso()]
        ]
    }

    # ----- TEST 1: No cookie (current broken behaviour) -----
    test_request(
        "TEST 1: No cookie (baseline - should be truncated)",
        {**OUTER_HEADERS},
        inner
    )
    time.sleep(1)

    # ----- TEST 2: Cookie in outer headers (the fix) -----
    if cookie:
        outer_with_cookie = {**OUTER_HEADERS, "cookie": cookie}
        inner_fresh = {
            "path": "/platform/chapter-content",
            "method": "GET",
            "query": query,
            "headers": [
                ["authorization", token],
                ["x-request-time", now_iso()]
            ]
        }
        test_request(
            "TEST 2: Cookie in OUTER HTTP headers (the fix)",
            outer_with_cookie,
            inner_fresh
        )
        time.sleep(1)

    # ----- TEST 3: Minimal cookie (just fz_access_token) -----
    if cookie and "fz_access_token=" in cookie:
        # Extract just the fz_access_token part
        parts = cookie.split(";")
        fz_token_part = [p.strip() for p in parts if p.strip().startswith("fz_access_token=")]
        if fz_token_part:
            minimal_cookie = fz_token_part[0]
            outer_minimal = {**OUTER_HEADERS, "cookie": minimal_cookie}
            inner_fresh2 = {
                "path": "/platform/chapter-content",
                "method": "GET",
                "query": query,
                "headers": [
                    ["authorization", token],
                    ["x-request-time", now_iso()]
                ]
            }
            test_request(
                "TEST 3: Only fz_access_token cookie (minimal auth)",
                outer_minimal,
                inner_fresh2
            )

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*60}")
    for name, status, code, length in results:
        marker = "✓ FULL" if length > 4000 else "✗ TRUNCATED" if length > 0 else "✗ EMPTY"
        print(f"  [{marker}] {length:>6} chars  |  {name}")
    
    print(f"\nResults written to diagnose_results.txt")
    
    with open("diagnose_results.txt", "w", encoding="utf-8") as f:
        f.write("FictionZone Diagnostic Results\n")
        f.write(f"Timestamp: {now_iso()}\n\n")
        for name, status, code, length in results:
            f.write(f"{name}: status={status} code={code} content_length={length}\n")

if __name__ == "__main__":
    main()
