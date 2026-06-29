"""Step 1 (part B): turn a gateway chapter response into a clean .txt file.

Designed to lose zero text. The content string is kept verbatim except
for:
  * \\r\\n → \\n  (Windows-line-ending normalisation)
  * trailing whitespace on each line is stripped (does NOT delete content)
  * triple+ blank lines collapsed to exactly two (visual breathing room)

Output layout:
    books/<novel_id>/chapters/<idx:04d> - <safe_title>.txt

The file starts with a banner containing chapter number, title, id, and
character count so the EPUB step has metadata to work with.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def normalize_text(raw: str) -> str:
    """Normalise line endings + collapse excessive blank lines.

    100% text retention: every non-whitespace character that appears in
    `raw` is preserved in the output. Only line endings and trailing
    whitespace are touched.
    """
    if not raw:
        return ""
    # 1. Normalise line endings
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # 2. Strip trailing whitespace from each line
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    # 3. Collapse 3+ consecutive blank lines down to exactly 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + "\n"


def banner(novel_id: str, data: dict) -> str:
    title = data.get("title", "Untitled")
    idx = data.get("idx", "?")
    chapter_id = data.get("id", "?")
    n_chars = len(data.get("content", ""))
    width = max(40, len(title) + 16)
    bar = "=" * width
    return (
        f"{bar}\n"
        f"  {title}\n"
        f"  Chapter {idx}\n"
        f"{bar}\n"
        f"  novel_id:   {novel_id}\n"
        f"  chapter_id: {chapter_id}\n"
        f"  characters: {n_chars}\n"
        f"{bar}\n\n"
    )


def save_chapter(novel_id: str, response: dict,
                 force: bool = False) -> Path:
    """Write a chapter response to books/<novel_id>/chapters/ and return the path."""
    if not response.get("success"):
        raise ValueError("response.success is false; nothing to save")

    data = response.get("data", {}) or {}
    raw_content = data.get("content", "")
    if not raw_content:
        raise ValueError("response.data.content is empty")

    title = data.get("title") or "Untitled"
    idx = data.get("idx", 0)
    safe_title = common.safe_filename(title, fallback="Untitled")

    novel_path = common.novel_dir(novel_id)
    chapters_dir = novel_path / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    fname = f"{int(idx):04d} - {safe_title}.txt"
    out = chapters_dir / fname

    if out.exists() and not force:
        return out  # already saved, idempotent

    body = normalize_text(raw_content)
    out.write_text(banner(novel_id, data) + body, encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a chapter response to .txt")
    parser.add_argument("novel_id")
    parser.add_argument("response_file", type=Path,
                        help="JSON file containing the gateway response "
                             "(as written by fetch_chapter.py)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite the .txt even if it already exists")
    args = parser.parse_args()

    response = json.loads(args.response_file.read_text(encoding="utf-8"))
    try:
        path = save_chapter(args.novel_id, response, force=args.force)
    except ValueError as err:
        print(f"[FAIL] {err}")
        return 1

    data = response.get("data", {}) or {}
    print(f"[OK] saved: {path}")
    print(f"      title:    {data.get('title')}")
    print(f"      idx:      {data.get('idx')}")
    print(f"      chars:    {len(data.get('content', ''))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
