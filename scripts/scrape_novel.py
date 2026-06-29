"""Step 4: scrape a whole novel with random delays between requests.

Pipeline:
  1. Ensure books/<novel_id>/chapters.json exists (runs fetch_chapter_list if not).
  2. For each chapter, in idx order, fetch + save as .txt.
  3. Sleep a random duration in [delay-min, delay-max] between requests.
  4. Skip chapters that are already on disk (resume-safe).
  5. Hard-stop on too many consecutive failures (--max-failures).

Usage:
    python scrape_novel.py <novel_id> [--delay-min 2] [--delay-max 6] \\
        [--start 1] [--end 50] [--force] [--max-failures 5]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import save_chapter  # noqa: E402
from fetch_chapter_list import fetch_all as fetch_chapter_list_all  # noqa: E402


def ensure_chapter_index(novel_id: str, force_refresh: bool) -> list[dict]:
    """Return the list of {idx,id,title} entries, fetching if needed."""
    index_path = common.novel_dir(novel_id) / "chapters.json"
    if index_path.exists() and not force_refresh:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        chapters = payload.get("chapters", [])
        if chapters:
            return chapters
        print(f"[INFO] {index_path} empty, re-fetching...")

    chapters = fetch_chapter_list_all(novel_id)
    if not chapters:
        raise SystemExit(f"[FAIL] no chapters returned for novel {novel_id}")
    index_path.write_text(
        json.dumps({"novel_id": str(novel_id), "count": len(chapters),
                    "chapters": chapters}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return chapters


def chapter_is_saved(novel_id: str, entry: dict) -> bool:
    """A chapter counts as 'saved' if any .txt file for its idx already exists."""
    chapters_dir = common.novel_dir(novel_id) / "chapters"
    idx = entry.get("idx")
    if idx is None:
        return False
    for path in chapters_dir.glob(f"{int(idx):04d} - *.txt"):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape every chapter of a novel")
    parser.add_argument("novel_id")
    parser.add_argument("--delay-min", type=float, default=2.0,
                        help="Minimum seconds between requests (default 2)")
    parser.add_argument("--delay-max", type=float, default=6.0,
                        help="Maximum seconds between requests (default 6)")
    parser.add_argument("--start", type=int, default=None,
                        help="First chapter idx to fetch (inclusive)")
    parser.add_argument("--end", type=int, default=None,
                        help="Last chapter idx to fetch (inclusive)")
    parser.add_argument("--max", type=int, default=None,
                        help="Maximum number of new chapters to fetch this run")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch every chapter even if already on disk")
    parser.add_argument("--refresh-index", action="store_true",
                        help="Discard cached chapters.json and re-fetch the index")
    parser.add_argument("--max-failures", type=int, default=5,
                        help="Stop after this many consecutive failures")
    parser.add_argument("--highlight", action="store_true",
                        help="Pass highlight=true to the gateway")
    parser.add_argument("--renumber", action="store_true",
                        help="Overwrite data.idx with the chapter's position in "
                             "chapters.json so output files sort 0001..0255. "
                             "Use this when the server's idx field is unreliable.")
    args = parser.parse_args()

    if args.delay_min < 0 or args.delay_max < args.delay_min:
        parser.error("--delay-min must be >= 0 and <= --delay-max")

    print(f"[INFO] HTTP backend: {common.backend_name()}")
    print(f"[INFO] Loading chapter index for novel {args.novel_id} ...")
    chapters = ensure_chapter_index(args.novel_id, args.refresh_index)
    print(f"[INFO] {len(chapters)} chapters indexed")

    # Apply start / end / max windows
    selected = []
    for entry in chapters:
        idx = entry.get("idx", 0) or 0
        if args.start is not None and idx < args.start:
            continue
        if args.end is not None and idx > args.end:
            continue
        selected.append(entry)
    if args.max is not None:
        selected = selected[: args.max]

    if not selected:
        print("[INFO] Nothing to do.")
        return 0

    pending = [
        e for e in selected
        if args.force or not chapter_is_saved(args.novel_id, e)
    ]
    print(f"[INFO] {len(pending)} of {len(selected)} chapters still to fetch "
          f"({len(selected) - len(pending)} cached)")

    consecutive_failures = 0
    fetched = 0
    started = time.time()

    for i, entry in enumerate(pending, start=1):
        title = entry.get("title") or f"Chapter {entry.get('idx')}"
        idx = entry.get("idx")
        cid = entry.get("id")
        print(f"[{i}/{len(pending)}] idx={idx} id={cid} - {title}")

        response = common.post_gateway_safe(
            "/platform/chapter-content",
            {
                "novel_id": str(args.novel_id),
                "chapter_id": str(cid),
                "highlight": bool(args.highlight),
            },
        )

        if response.get("success") and args.renumber:
            data_block = response.setdefault("data", {})
            if isinstance(data_block, dict):
                data_block["idx"] = i

        if not response.get("success"):
            consecutive_failures += 1
            print(f"  [FAIL] {response.get('error') or response.get('reason')} "
                  f"(consecutive {consecutive_failures}/{args.max_failures})")
            if response.get("cf_ray"):
                print(f"         cf-ray: {response['cf_ray']}")
            if consecutive_failures >= args.max_failures:
                print("[ABORT] too many consecutive failures, bailing out")
                return 2
        else:
            try:
                path = save_chapter.save_chapter(args.novel_id, response)
            except ValueError as err:
                print(f"  [FAIL] save: {err}")
                consecutive_failures += 1
                if consecutive_failures >= args.max_failures:
                    return 2
            else:
                fetched += 1
                consecutive_failures = 0
                print(f"  [OK] {path.name}")

        # Random delay between requests (skip after the last)
        if i < len(pending):
            delay = common.jitter_sleep(args.delay_min, args.delay_max)
            print(f"  ...sleeping {delay:.2f}s")

    elapsed = time.time() - started
    print(f"\n[DONE] fetched {fetched} new chapter(s) in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())