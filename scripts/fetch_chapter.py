"""Step 1 (part A): fetch a single chapter's response from the gateway.

Usage:
    python fetch_chapter.py <novel_id> <chapter_id> [--highlight] [--print]

Returns / prints the raw `data` block of the gateway response. Pair this
with `save_chapter.py` to write the content to disk.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/fetch_chapter.py ...` from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a single chapter from fictionzone.net")
    parser.add_argument("novel_id", help="e.g. 27413")
    parser.add_argument("chapter_id", help="e.g. 1806738")
    parser.add_argument("--highlight", action="store_true",
                        help="Request highlighted content (matches browser default)")
    parser.add_argument("--print", action="store_true", help="Print the full response JSON")
    args = parser.parse_args()

    response = common.post_gateway_safe(
        "/platform/chapter-content",
        {
            "novel_id": str(args.novel_id),
            "chapter_id": str(args.chapter_id),
            "highlight": bool(args.highlight),
        },
    )

    if not response.get("success"):
        print(f"[FAIL] {response.get('error') or response.get('reason')}")
        if response.get("cf_ray"):
            print(f"  cf-ray: {response['cf_ray']}")
        if response.get("body_snippet"):
            print(f"  body:   {response['body_snippet']}")
        return 1

    if args.print:
        print(json.dumps(response, indent=2, ensure_ascii=False))
    else:
        data = response.get("data", {}) or {}
        print(f"[OK] {data.get('title', '?')} (idx={data.get('idx')}) "
              f"- {len(data.get('content', ''))} chars")

    # Always dump the full response for piping
    print("__RESPONSE_JSON__")
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
