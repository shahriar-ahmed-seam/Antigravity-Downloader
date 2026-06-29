"""Step 2: scrape the book info page and persist metadata + cover.

Fetches https://fictionzone.net/novel/<slug> with browser TLS, extracts:
  * title, author, description, status, genres, tags
  * cover image URL → downloads to books/<novel_id>/cover.<ext>
  * novel_id (from the page if discoverable, else from --novel-id)

Sources, in priority order:
  1. JSON-LD <script type="application/ld+json"> blocks
  2. Open Graph + Twitter meta tags
  3. Inline HTML fallbacks
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


# --- regex helpers ---------------------------------------------------------
_META_RE = re.compile(
    r"""<meta\s+[^>]*?(?:name|property)=["']([^"']+)["']\s+[^>]*?content=["']([^"']*)["']""",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
_SRC_RE = re.compile(r"""src=["']([^"']+)["']""", re.IGNORECASE)


def _as_dict(meta_name: str) -> bool:
    """Return True for keys whose value is a dict/object (e.g. og:image)."""
    return False


def parse_meta(html: str) -> dict:
    """Pull every <meta name|property=... content=...> tag into a flat dict."""
    out: dict[str, str] = {}
    for key, value in _META_RE.findall(html):
        out[key.lower()] = value
    title_match = _TITLE_RE.search(html)
    if title_match:
        out.setdefault("html:title", title_match.group(1).strip())
    return out


def parse_jsonld(html: str) -> list[dict]:
    """Parse every JSON-LD block, returning dicts only."""
    blocks: list[dict] = []
    for raw in _JSONLD_RE.findall(html):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            # Try to fix the common "trailing comma" issue
            try:
                obj = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except json.JSONDecodeError:
                continue
        if isinstance(obj, dict):
            blocks.append(obj)
        elif isinstance(obj, list):
            blocks.extend(b for b in obj if isinstance(b, dict))
    return blocks


def find_cover_url(html: str, meta: dict) -> Optional[str]:
    for key in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        if meta.get(key):
            return meta[key]
    # Last-ditch: first <img> inside a "cover"-like container
    cover_div = re.search(
        r'(?is)<div[^>]*class=["\'][^"\']*cover[^"\']*["\'][^>]*>(.*?)</div>',
        html,
    )
    if cover_div:
        m = _SRC_RE.search(cover_div.group(1))
        if m:
            return m.group(1)
    return None


def find_description(html: str, meta: dict, jsonld_blocks: list[dict]) -> str:
    for block in jsonld_blocks:
        if isinstance(block.get("description"), str) and block["description"].strip():
            return block["description"].strip()
    for key in ("og:description", "twitter:description", "description"):
        if meta.get(key):
            return meta[key].strip()
    return ""


def find_author(meta: dict, jsonld_blocks: list[dict]) -> str:
    for block in jsonld_blocks:
        author = block.get("author")
        if isinstance(author, dict):
            name = author.get("name")
            if name:
                return str(name).strip()
        if isinstance(author, str) and author.strip():
            return author.strip()
    return meta.get("author", "").strip() or meta.get("book:author", "").strip()


def find_genres(html: str, meta: dict) -> list[str]:
    raw = meta.get("book:tag", "") or meta.get("keywords", "")
    if raw:
        return [t.strip() for t in re.split(r"[,;|]", raw) if t.strip()]
    # Inline genre list (fictionzone uses <a class="genre">...)
    matches = re.findall(
        r'(?is)<a[^>]+class=["\'][^"\']*genre[^"\']*["\'][^>]*>([^<]+)</a>',
        html,
    )
    return [m.strip() for m in matches if m.strip()]


def find_novel_id_from_html(html: str) -> Optional[str]:
    """The page often embeds the novel id in inline scripts or data attrs."""
    patterns = [
        r'"novel_id"\s*:\s*"?(\d+)"?',
        r'"novelId"\s*:\s*"?(\d+)"?',
        r'data-novel-id=["\']?(\d+)["\']?',
        r'/novel/[^/]+/(\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def build_info(html: str, page_url: str, fallback_novel_id: Optional[str]) -> dict:
    meta = parse_meta(html)
    jsonld = parse_jsonld(html)

    title = (meta.get("og:title")
             or meta.get("twitter:title")
             or meta.get("html:title")
             or "").strip()
    # Strip " - FictionZone" suffix if present
    title = re.sub(r"\s*[-|–—]\s*FictionZone\s*$", "", title, flags=re.IGNORECASE)

    description = find_description(html, meta, jsonld)
    author = find_author(meta, jsonld)
    cover_url = find_cover_url(html, meta)
    if cover_url:
        cover_url = urljoin(page_url, cover_url)
    genres = find_genres(html, meta)
    status = meta.get("book:status", "").strip()

    novel_id = find_novel_id_from_html(html) or fallback_novel_id or ""

    info = {
        "novel_id": str(novel_id),
        "title": title,
        "author": author,
        "description": description,
        "cover_url": cover_url,
        "status": status,
        "genres": genres,
        "source_url": page_url,
    }
    return info


def download_cover(cover_url: str, dest_dir: Path) -> Optional[Path]:
    """Download the cover image, preserving its extension. Returns path or None."""
    try:
        data = common.get_bytes(cover_url)
    except Exception as err:  # noqa: BLE001
        print(f"[WARN] cover download failed: {err}")
        return None

    ext_match = re.search(r"\.([a-zA-Z0-9]{2,5})(?:\?|$)", cover_url)
    ext = (ext_match.group(1).lower() if ext_match else "jpg")
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        ext = "jpg"

    out = dest_dir / f"cover.{ext}"
    out.write_bytes(data)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape book info page")
    parser.add_argument("url", help="Full URL to /novel/<slug>")
    parser.add_argument("--novel-id", default=None,
                        help="Fallback novel id if not discoverable in the page")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Override the books/<novel_id>/ directory")
    parser.add_argument("--skip-cover", action="store_true",
                        help="Do not download the cover image")
    args = parser.parse_args()

    print(f"[INFO] HTTP backend: {common.backend_name()}")
    print(f"[INFO] Fetching {args.url} ...")

    try:
        html = common.get_html(args.url)
    except Exception as err:  # noqa: BLE001
        print(f"[FAIL] {err}")
        return 1

    info = build_info(html, args.url, args.novel_id)
    if not info["novel_id"]:
        print("[FAIL] could not determine novel_id; pass --novel-id")
        return 1

    out_dir = args.out_dir or common.novel_dir(info["novel_id"])

    cover_path: Optional[Path] = None
    if info["cover_url"] and not args.skip_cover:
        cover_path = download_cover(info["cover_url"], out_dir)
        if cover_path:
            info["cover_path"] = str(cover_path.relative_to(common.BOOKS_ROOT))

    info_path = out_dir / "info.json"
    info_path.write_text(
        json.dumps(info, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"[OK] novel_id : {info['novel_id']}")
    print(f"     title    : {info['title']}")
    print(f"     author   : {info['author']}")
    print(f"     cover    : {info['cover_url'] or '(none)'}")
    if cover_path:
        print(f"     saved to : {cover_path}")
    print(f"     info.json: {info_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())