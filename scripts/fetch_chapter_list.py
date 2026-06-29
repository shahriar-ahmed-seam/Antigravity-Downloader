"""Step 3: fetch the full chapter index for a novel.

POSTs to /platform/chapter-lists and saves a normalised list of
{idx, id, title} entries to books/<novel_id>/chapters.json.

The site has been observed to paginate large novels. This script walks
all pages until it stops seeing new chapters.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def _normalise_entries(raw: Iterable[dict]) -> list[dict]:
    """Convert whatever the gateway returns into a clean [{idx,id,title}] list."""
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("id") or entry.get("chapter_id") or entry.get("_id")
        title = entry.get("title") or entry.get("name") or ""
        idx = entry.get("idx") or entry.get("order") or entry.get("index") or entry.get("chapter_no")
        if cid is None:
            continue
        try:
            idx_int = int(idx) if idx is not None else None
        except (TypeError, ValueError):
            idx_int = None
        out.append({
            "id": str(cid),
            "title": str(title).strip(),
            "idx": idx_int,
        })
    # Sort by idx when we have it; otherwise preserve order
    out.sort(key=lambda e: (e["idx"] is None, e["idx"] if e["idx"] is not None else 0, e["id"]))
    # Re-number idx 1..N if everything was missing it
    if all(e["idx"] is None for e in out):
        for i, e in enumerate(out, start=1):
            e["idx"] = i
    return out


def fetch_all(novel_id: str, page_size: int = 200, max_pages: int = 50) -> list[dict]:
    """Walk paginated responses until exhausted or max_pages hit."""
    collected: list[dict] = []
    seen_ids: set[str] = set()
    page = 1

    while page <= max_pages:
        response = common.post_gateway_safe(
            "/platform/chapter-lists",
            {
                "novel_id": str(novel_id),
                "page": page,
                "page_size": page_size,
            },
        )
        if not response.get("success"):
            print(f"[WARN] page {page} failed: {response.get('error') or response.get('reason')}")
            break

        data = response.get("data", {}) or {}
        # Accept either {chapters: [...], total: N} or a bare list
        raw_list = data.get("chapters") or data.get("list") or data.get("items") or []
        if not raw_list and isinstance(data, list):
            raw_list = data
        if not raw_list:
            break

        new_count = 0
        for entry in _normalise_entries(raw_list):
            if entry["id"] in seen_ids:
                continue
            seen_ids.add(entry["id"])
            collected.append(entry)
            new_count += 1

        print(f"  page {page}: +{new_count} chapters (running total {len(collected)})")

        total = data.get("total") or data.get("total_count")
        if total is not None:
            try:
                if len(collected) >= int(total):
                    break
            except (TypeError, ValueError):
                pass
        if new_count == 0 or new_count < len(raw_list):
            break  # server gave us a partial page → pagination done
        page += 1

    return collected


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the chapter list for a novel")
    parser.add_argument("novel_id")
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--out", type=Path, default=None,
                        help="Override output path (default: books/<novel_id>/chapters.json)")
    args = parser.parse_args()

    print(f"[INFO] HTTP backend: {common.backend_name()}")
    print(f"[INFO] Fetching chapter list for novel_id={args.novel_id}...")

    chapters = fetch_all(args.novel_id, page_size=args.page_size, max_pages=args.max_pages)

    if not chapters:
        print("[FAIL] no chapters returned")
        return 1

    out = args.out or (common.novel_dir(args.novel_id) / "chapters.json")
    payload = {
        "novel_id": str(args.novel_id),
        "count": len(chapters),
        "chapters": chapters,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] wrote {len(chapters)} chapters -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())