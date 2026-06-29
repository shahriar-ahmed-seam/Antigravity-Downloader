"""Step 5: compile the saved chapter .txt files into a single .epub.

Layout assumed:
    books/<novel_id>/
        info.json
        cover.<ext>
        chapters.json
        chapters/<idx:04d> - <title>.txt

Primary path: `ebooklib` (well-tested, handles EPUB2/3 correctly).
Fallback:   a hand-rolled minimal EPUB3 built with `zipfile`, so the
             script still works if ebooklib isn't installed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
BANNER_LINE = "=" * 40
BANNER_RE = re.compile(
    rf"^{re.escape(BANNER_LINE)}\n"
    r"  (?P<title>.+?)\n"
    r"  Chapter (?P<idx>\S+)\n"
    rf"{re.escape(BANNER_LINE)}\n"
    r"  novel_id:.*\n"
    r"  chapter_id:.*\n"
    r"  characters:.*\n"
    rf"{re.escape(BANNER_LINE)}\n\n",
    re.MULTILINE,
)


def _split_banner(text: str) -> tuple[str, str]:
    """Strip the banner block written by save_chapter.py, return (title, body)."""
    m = BANNER_RE.match(text)
    if not m:
        return "", text
    return m.group("title").strip(), text[m.end():]


def _paragraphs_to_html(body: str) -> str:
    """Convert a plain-text body into a sequence of <p> elements."""
    paragraphs = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    if not paragraphs:
        return "<p></p>"
    return "\n".join(f"<p>{escape(p.strip())}</p>" for p in paragraphs)


def _load_index(novel_dir: Path) -> tuple[list[dict], Path]:
    chapters_json = novel_dir / "chapters.json"
    if not chapters_json.exists():
        raise SystemExit(f"[FAIL] missing {chapters_json} - run fetch_chapter_list.py first")
    payload = json.loads(chapters_json.read_text(encoding="utf-8"))
    return payload.get("chapters", []), chapters_json


def _dedup_by_idx(chapters: list[dict]) -> list[dict]:
    """Drop duplicate idx entries, keeping the first occurrence.

    The fictionzone chapter-list endpoint returns overlapping idx values
    across pages (e.g. page 1 has idx 1-200, page 2 has idx 1-200 plus
    201-255), so the same chapter can show up twice. We need unique idx
    values to avoid duplicate .xhtml entries in the final EPUB.
    """
    seen: set = set()
    out: list[dict] = []
    for entry in chapters:
        idx = entry.get("idx")
        if idx is None or idx in seen:
            continue
        seen.add(idx)
        out.append(entry)
    return out


def _load_info(novel_dir: Path) -> dict:
    info_path = novel_dir / "info.json"
    if not info_path.exists():
        return {
            "novel_id": novel_dir.name,
            "title": f"Novel {novel_dir.name}",
            "author": "Unknown",
            "description": "",
            "cover_path": None,
        }
    return json.loads(info_path.read_text(encoding="utf-8"))


def _find_chapter_file(novel_dir: Path, idx: int) -> Optional[Path]:
    """Return the chapter .txt path matching idx, or None."""
    chapters_dir = novel_dir / "chapters"
    matches = list(chapters_dir.glob(f"{int(idx):04d} - *.txt"))
    if matches:
        return matches[0]
    # Fall back: the first file whose leading 4 digits are idx
    matches = sorted(chapters_dir.glob("*.txt"))
    for p in matches:
        m = re.match(r"^(\d{4}) - ", p.name)
        if m and int(m.group(1)) == idx:
            return p
    return None


# ---------------------------------------------------------------------------
# Primary path: ebooklib
# ---------------------------------------------------------------------------
def _compile_with_ebooklib(novel_dir: Path, novel_id: str, info: dict,
                           chapters: list[dict], out_path: Path) -> Path:
    from ebooklib import epub  # type: ignore

    # Modern ebooklib removed EpubBook.get_type(); EpubWriter still calls it.
    # Re-add a no-op shim so write_epub() succeeds without forking the lib.
    if not hasattr(epub.EpubBook, "get_type"):
        epub.EpubBook.get_type = lambda self: "epub"

    book = epub.EpubBook()
    book.set_identifier(f"fictionzone-{novel_id}")
    book.set_title(info.get("title") or f"Novel {novel_id}")
    book.set_language("en")
    author = info.get("author") or "Unknown"
    book.add_author(author)
    book.add_metadata("DC", "description", info.get("description", ""))

    # Cover
    cover_path_str = info.get("cover_path")
    cover_path = (
        common.BOOKS_ROOT / cover_path_str if cover_path_str
        else _find_cover_file(novel_dir)
    )
    if cover_path and cover_path.exists():
        ext = cover_path.suffix.lstrip(".").lower() or "jpeg"
        # ebooklib expects "jpeg" not "jpg"
        if ext == "jpg":
            ext = "jpeg"
        with cover_path.open("rb") as fh:
            book.set_cover("cover." + ext, fh.read())

    # Chapters
    epub_chapters: list = []
    spine: list = ["nav"]
    toc: list = []

    for entry in chapters:
        idx = entry.get("idx")
        cid = entry.get("id")
        title = entry.get("title") or f"Chapter {idx}"
        if idx is None:
            continue
        path = _find_chapter_file(novel_dir, idx)
        if path is None:
            print(f"  [WARN] idx {idx}: no .txt file, skipping")
            continue
        text = path.read_text(encoding="utf-8")
        _, body = _split_banner(text)
        html_body = _paragraphs_to_html(body)

        chapter = epub.EpubHtml(
            title=title,
            file_name=f"chap_{int(idx):04d}.xhtml",
            lang="en",
        )
        chapter.content = (
            f"<h1>{escape(title)}</h1>\n"
            f"<p><em>Chapter {idx}</em></p>\n"
            f"{html_body}"
        )
        chapter.add_item(book)
        epub_chapters.append(chapter)
        toc.append(chapter)
        spine.append(chapter)

    if not epub_chapters:
        raise SystemExit("[FAIL] no chapter files found to include")

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(out_path), book)
    return out_path


def _find_cover_file(novel_dir: Path) -> Optional[Path]:
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = novel_dir / f"cover.{ext}"
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Fallback path: hand-rolled EPUB3 via zipfile
# ---------------------------------------------------------------------------
def _minimal_escape(text: str) -> str:
    return xml_escape(text, {'"': "&quot;", "'": "&apos;"})


def _compile_with_zipfile(novel_dir: Path, novel_id: str, info: dict,
                          chapters: list[dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    title = info.get("title") or f"Novel {novel_id}"
    author = info.get("author") or "Unknown"
    description = info.get("description", "")
    cover_path = (
        common.BOOKS_ROOT / info["cover_path"] if info.get("cover_path")
        else _find_cover_file(novel_dir)
    )
    cover_mime = None
    cover_data = None
    cover_name = None
    if cover_path and cover_path.exists():
        suffix = cover_path.suffix.lstrip(".").lower()
        cover_mime = {
            "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp", "gif": "image/gif",
        }.get(suffix, "image/jpeg")
        cover_name = f"cover{suffix}"
        cover_data = cover_path.read_bytes()

    items: list[tuple[str, bytes, str]] = []
    manifest: list[str] = []
    spine: list[str] = []

    # 1. mimetype (must be first, uncompressed)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)

    # 2. META-INF/container.xml
    items.append((
        "META-INF/container.xml",
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        b'<rootfiles><rootfile full-path="OEBPS/content.opf" '
        b'media-type="application/oebps-package+xml"/></rootfiles></container>',
        "application/xml",
    ))

    # 3. Cover
    if cover_data is not None:
        items.append((f"OEBPS/{cover_name}", cover_data, cover_mime))
        manifest.append(
            f'<item id="cover-img" href="{cover_name}" media-type="{cover_mime}" '
            f'properties="cover-image"/>'
        )
        spine.append(f'<itemref idref="cover-img"/>')

    # 4. Chapters
    chapter_entries: list[dict] = []
    missing_idxs: list[int] = []
    for entry in chapters:
        idx = entry.get("idx")
        title = entry.get("title") or f"Chapter {idx}"
        if idx is None:
            continue
        path = _find_chapter_file(novel_dir, idx)
        if path is None:
            missing_idxs.append(idx)
            continue
        text = path.read_text(encoding="utf-8")
        _, body = _split_banner(text)
        body_html = _paragraphs_to_html(body)
        chapter_id = f"chap{idx:04d}"
        chapter_file = f"{chapter_id}.xhtml"
        xhtml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" lang="en">'
            f'<head><meta charset="utf-8"/>'
            f'<title>{_minimal_escape(title)}</title></head>'
            f'<body><h1>{_minimal_escape(title)}</h1>'
            f'<p><em>Chapter {idx}</em></p>{body_html}</body></html>'
        )
        items.append((f"OEBPS/{chapter_file}", xhtml.encode("utf-8"),
                      "application/xhtml+xml"))
        manifest.append(
            f'<item id="{chapter_id}" href="{chapter_file}" '
            f'media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{chapter_id}"/>')
        chapter_entries.append({"title": title, "file": chapter_file})

    if not chapter_entries:
        raise SystemExit("[FAIL] no chapter files found to include")
    if missing_idxs:
        # One consolidated summary line instead of 250 individual warnings
        sample = missing_idxs[:10]
        suffix = "..." if len(missing_idxs) > 10 else ""
        print(f"  [WARN] {len(missing_idxs)} chapter(s) had no .txt file "
              f"(first: {sample}{suffix})")

    # 5. NAV
    nav_items = "\n".join(
        f'<li><a href="{c["file"]}">{_minimal_escape(c["title"])}</a></li>'
        for c in chapter_entries
    )
    nav = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" lang="en">'
        f'<head><meta charset="utf-8"/><title>Table of Contents</title></head>'
        f'<body><nav epub:type="toc" id="toc"><h1>Table of Contents</h1>'
        f'<ol>{nav_items}</ol></nav></body></html>'
    )
    items.append(("OEBPS/nav.xhtml", nav.encode("utf-8"),
                  "application/xhtml+xml"))
    manifest.append(
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav"/>'
    )
    spine.append('<itemref idref="nav"/>')

    # 6. content.opf
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    opf = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        f'unique-identifier="bookid" lang="en">'
        f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="bookid">fictionzone-{_minimal_escape(str(novel_id))}</dc:identifier>'
        f'<dc:title>{_minimal_escape(title)}</dc:title>'
        f'<dc:creator>{_minimal_escape(author)}</dc:creator>'
        f'<dc:language>en</dc:language>'
        f'<dc:description>{_minimal_escape(description)}</dc:description>'
        f'<meta property="dcterms:modified">{now}</meta>'
        f'</metadata>'
        f'<manifest>{"".join(manifest)}</manifest>'
        f'<spine>{"".join(spine)}</spine>'
        f'</package>'
    )
    items.append(("OEBPS/content.opf", opf.encode("utf-8"),
                  "application/oebps-package+xml"))

    # Single handle, write mode. The first entry (mimetype) is added with
    # ZIP_STORED per the EPUB spec; everything else uses the default deflate.
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, (name, data, _mime) in enumerate(items):
            compress = zipfile.ZIP_STORED if idx == 0 else zipfile.ZIP_DEFLATED
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = compress
            zf.writestr(info, data)

    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Compile chapters into an .epub")
    parser.add_argument("novel_id")
    parser.add_argument("--out", type=Path, default=None,
                        help="Override output .epub path")
    parser.add_argument("--no-ebooklib", action="store_true",
                        help="Skip the ebooklib path and use the zipfile fallback")
    args = parser.parse_args()

    novel_dir = common.novel_dir(args.novel_id)
    chapters, _ = _load_index(novel_dir)
    info = _load_info(novel_dir)

    safe_title = common.safe_filename(info.get("title") or f"Novel {args.novel_id}")
    out_path = args.out or (novel_dir / f"{safe_title}.epub")
    print(f"[INFO] Compiling {len(chapters)} chapters -> {out_path}")

    if not args.no_ebooklib:
        try:
            import ebooklib  # noqa: F401
            _compile_with_ebooklib(novel_dir, args.novel_id, info, chapters, out_path)
            print(f"[OK] wrote {out_path} (ebooklib)")
            return 0
        except ImportError:
            print("[INFO] ebooklib not installed, using zipfile fallback")
        except Exception as err:  # noqa: BLE001
            print(f"[WARN] ebooklib failed ({err!r}), falling back to zipfile")

    _compile_with_zipfile(novel_dir, args.novel_id, info, chapters, out_path)
    print(f"[OK] wrote {out_path} (zipfile fallback)")
    return 0


if __name__ == "__main__":
    sys.exit(main())