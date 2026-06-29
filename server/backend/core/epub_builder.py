import html
import json
import logging
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Union
from xml.sax.saxutils import escape as xml_escape

from backend.config import BOOKS_DIR
from backend.core.cache import CacheManager, safe_filename
from backend.core.exceptions import EpubBuildError

logger = logging.getLogger("novel_downloader.epub")


def parse_chapter_file(file_path: Path) -> tuple[dict[str, Any], str]:
    """Parse the chapter text file, extracting banner metadata and text body.

    Supports dynamic banner bar widths to resolve the fragile regex parsing bug,
    and supports the new clean text format (title + content).
    """
    text = file_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    meta = {}
    body_start_idx = 0

    # Ensure it looks like a standard banner (starts with dynamic bar of '=' signs)
    if len(lines) >= 8 and lines[0].startswith("===") and lines[0].replace("=", "").strip() == "":
        meta["title"] = lines[1].strip()
        # Extract idx from "Chapter X"
        meta["idx"] = lines[2].replace("Chapter", "").strip()
        
        # Parse fields between middle and bottom bars
        for i in range(4, 7):
            if ":" in lines[i]:
                k, v = lines[i].split(":", 1)
                meta[k.strip()] = v.strip()
        
        # Body starts after the third bar
        body_start_idx = 8
        body = "\n".join(lines[body_start_idx:])
        return meta, body
    else:
        # Fallback to new clean format or just basic text file
        # Filename format: 0001 - Title.txt
        name = file_path.stem
        idx_str = "0"
        title = name
        if " - " in name:
            idx_part, title_part = name.split(" - ", 1)
            idx_str = idx_part
            # Use title from file content if available
            title = lines[0].strip() if lines else title_part
        else:
            title = lines[0].strip() if lines else name
        
        meta = {
            "title": title,
            "idx": idx_str,
            "chapter_id": name,  # fallback
            "novel_id": file_path.parent.parent.name
        }
        
        # Skip title and empty lines
        body_start = 1
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1
            
        body = "\n".join(lines[body_start:])
        return meta, body


def paragraphs_to_html(body: str) -> str:
    """Convert plain text newline separated paragraphs to HTML <p> tags.
    Preserves exact whitespace spacing and single newlines.
    """
    lines = body.split("\n")
    html_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            html_lines.append(f"<p>{html.escape(stripped)}</p>")
        else:
            html_lines.append("<p>&#160;</p>")
    return "\n".join(html_lines)


def minimal_escape(text: str) -> str:
    return xml_escape(text, {'"': "&quot;", "'": "&apos;"})


class EpubBuilder:
    """Intelligently builds and merges EPUB files from locally cached text files."""

    def __init__(self, cache_mgr: CacheManager):
        self.cache = cache_mgr

    def compile(self, novel_id: Union[str, int], range_start: Optional[int] = None,
                range_end: Optional[int] = None, force_zipfile: bool = True) -> Path:
        """Scan cached chapters, align with canonical chapters.json, and output EPUB.

        Performs intelligent sorting, deduplication, and range filtering.
        """
        novel_dir = self.cache.novel_dir(novel_id)
        info = self.cache.get_book_info(novel_id)
        canonical_chapters = self.cache.get_chapter_index(novel_id)

        if not canonical_chapters:
            raise EpubBuildError(f"Cannot compile: Chapter index (chapters.json) not found for novel {novel_id}")

        if not info:
            info = {
                "novel_id": str(novel_id),
                "title": f"Novel {novel_id}",
                "author": "Unknown",
                "description": "",
                "cover_path": None
            }

        # 1. Scan the chapters directory and parse files
        c_dir = self.cache.chapters_dir(novel_id)
        downloaded_chapters = {}  # chapter_id -> {meta, body}
        downloaded_by_idx = {}    # idx -> {meta, body}

        for p in c_dir.glob("*.txt"):
            try:
                meta, body = parse_chapter_file(p)
                cid = meta.get("chapter_id")
                idx_val = meta.get("idx")

                if cid:
                    downloaded_chapters[str(cid)] = {"meta": meta, "body": body}
                if idx_val is not None:
                    try:
                        downloaded_by_idx[int(idx_val)] = {"meta": meta, "body": body}
                    except ValueError:
                        pass
            except Exception as err:
                logger.error(f"Failed to parse chapter file {p.name}: {err}")

        # 2. Match downloaded chapters against canonical list to filter and sort
        chapters_to_include = []
        seen_ids = set()
        seen_idxs = set()
        for idx, entry in enumerate(canonical_chapters, start=1):
            cid = str(entry.get("id"))
            c_idx = entry.get("idx")
            c_title = entry.get("title") or f"Chapter {c_idx or idx}"

            # Apply range limit based on the canonical idx
            current_idx = c_idx if c_idx is not None else idx
            if range_start is not None and current_idx < range_start:
                continue
            if range_end is not None and current_idx > range_end:
                continue

            # Dedup to prevent duplicate files in EPUB zip
            if cid in seen_ids or current_idx in seen_idxs:
                continue

            # Attempt to retrieve content by chapter_id first, then fallback to idx
            content_data = downloaded_chapters.get(cid)
            if not content_data and c_idx is not None:
                content_data = downloaded_by_idx.get(int(c_idx))

            if content_data:
                seen_ids.add(cid)
                seen_idxs.add(current_idx)
                # Add to final set
                chapters_to_include.append({
                    "id": cid,
                    "idx": current_idx,
                    "title": c_title,
                    "body": content_data["body"]
                })

        if not chapters_to_include:
            raise EpubBuildError("No downloaded chapters match the requested range.")

        # Determine output path
        safe_title = safe_filename(info.get("title", f"Novel {novel_id}"))
        out_path = novel_dir / f"{safe_title}.epub"

        # Try EbookLib if requested, otherwise fallback to ZipFile
        if not force_zipfile:
            try:
                self._build_with_ebooklib(novel_id, info, chapters_to_include, out_path)
                return out_path
            except Exception as err:
                logger.warning(f"EbookLib failed to build EPUB: {err}. Falling back to zipfile method.")

        self._build_with_zipfile(novel_id, info, chapters_to_include, out_path)
        return out_path

    def _find_cover_file(self, novel_id: Union[str, int]) -> Optional[Path]:
        novel_dir = self.cache.novel_dir(novel_id)
        for ext in ("jpg", "jpeg", "png", "webp", "gif"):
            p = novel_dir / f"cover.{ext}"
            if p.exists():
                return p
        return None

    def _build_with_zipfile(self, novel_id: str, info: dict, chapters: list[dict], out_path: Path):
        """Build EPUB3 using pure zipfile module (robust, lightweight)."""
        title = info.get("title") or f"Novel {novel_id}"
        author = info.get("author") or "Unknown"
        description = info.get("description", "")
        
        # Cover resolution
        cover_path = self._find_cover_file(novel_id)
        cover_mime = None
        cover_data = None
        cover_name = None
        if cover_path:
            suffix = cover_path.suffix.lstrip(".").lower()
            cover_mime = {
                "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp", "gif": "image/gif",
            }.get(suffix, "image/jpeg")
            cover_name = f"cover.{suffix}"
            cover_data = cover_path.read_bytes()

        items = []
        manifest = []
        spine = []

        # 1. mimetype (first entry, must be uncompressed)
        # We handle this by writing mimetype in ZIP_STORED first, then closing and reopening in append mode.
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

        # 2. META-INF/container.xml
        items.append((
            "META-INF/container.xml",
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            b'<rootfiles><rootfile full-path="OEBPS/content.opf" '
            b'media-type="application/oebps-package+xml"/></rootfiles></container>',
            "application/xml",
        ))

        # 3. Add Cover and Info Page
        if cover_data is not None:
            items.append((f"OEBPS/{cover_name}", cover_data, cover_mime))
            manifest.append(
                f'<item id="cover-img" href="{cover_name}" media-type="{cover_mime}" '
                f'properties="cover-image"/>'
            )
            
            cover_xhtml = (
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" lang="en">'
                f'<head><meta charset="utf-8"/><title>Cover</title>'
                f'<style>body {{ text-align: center; margin: 0; padding: 0; }} '
                f'img {{ max-width: 100%; height: auto; }}</style></head>'
                f'<body><img src="{cover_name}" alt="Cover"/></body></html>'
            )
            items.append(("OEBPS/cover.xhtml", cover_xhtml.encode("utf-8"), "application/xhtml+xml"))
            manifest.append('<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
            spine.append('<itemref idref="cover"/>')

        # Info Page
        genres_str = ", ".join(info.get("genres", []))
        status = info.get("status", "Unknown")
        info_xhtml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" lang="en">'
            f'<head><meta charset="utf-8"/><title>Book Information</title></head>'
            f'<body>'
            f'<h1>{minimal_escape(title)}</h1>'
            f'<p><strong>Author:</strong> {minimal_escape(author)}</p>'
            f'<p><strong>Status:</strong> {minimal_escape(status)}</p>'
            f'<p><strong>Genres:</strong> {minimal_escape(genres_str)}</p>'
            f'<h3>Synopsis</h3>'
            f'<div>{paragraphs_to_html(description)}</div>'
            f'</body></html>'
        )
        items.append(("OEBPS/info.xhtml", info_xhtml.encode("utf-8"), "application/xhtml+xml"))
        manifest.append('<item id="info" href="info.xhtml" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="info"/>')

        # 4. Add Chapters
        chapter_entries = []
        for chap in chapters:
            c_id = chap["id"]
            c_idx = chap["idx"]
            c_title = chap["title"]
            body_html = paragraphs_to_html(chap["body"])

            file_id = f"chap{c_idx:04d}"
            file_name = f"{file_id}.xhtml"

            xhtml = (
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" lang="en">'
                f'<head><meta charset="utf-8"/>'
                f'<title>{minimal_escape(c_title)}</title></head>'
                f'<body><h1>{minimal_escape(c_title)}</h1>'
                f'<p><em>Chapter {c_idx}</em></p>{body_html}</body></html>'
            )

            items.append((f"OEBPS/{file_name}", xhtml.encode("utf-8"), "application/xhtml+xml"))
            manifest.append(f'<item id="{file_id}" href="{file_name}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="{file_id}"/>')
            chapter_entries.append({"title": c_title, "file": file_name})

        # 5. Table of Contents (nav.xhtml)
        nav_items = "\n".join(
            f'<li><a href="{c["file"]}">{minimal_escape(c["title"])}</a></li>'
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
        items.append(("OEBPS/nav.xhtml", nav.encode("utf-8"), "application/xhtml+xml"))
        manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        spine.append('<itemref idref="nav"/>')

        # 6. Metadata Package descriptor (content.opf)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        opf = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            f'unique-identifier="bookid" lang="en">'
            f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:identifier id="bookid">fictionzone-{minimal_escape(str(novel_id))}</dc:identifier>'
            f'<dc:title>{minimal_escape(title)}</dc:title>'
            f'<dc:creator>{minimal_escape(author)}</dc:creator>'
            f'<dc:language>en</dc:language>'
            f'<dc:description>{minimal_escape(description)}</dc:description>'
            f'<meta property="dcterms:modified">{now_str}</meta>'
            f'</metadata>'
            f'<manifest>{"".join(manifest)}</manifest>'
            f'<spine>{"".join(spine)}</spine>'
            f'</package>'
        )
        items.append(("OEBPS/content.opf", opf.encode("utf-8"), "application/oebps-package+xml"))

        # Write remaining zipped items in append mode
        with zipfile.ZipFile(out_path, "a", zipfile.ZIP_DEFLATED) as zf:
            for name, data, _mime in items:
                # Store files using 1980 time default to preserve deterministic byte builds
                z_info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
                z_info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(z_info, data)

    def _build_with_ebooklib(self, novel_id: str, info: dict, chapters: list[dict], out_path: Path):
        """Assemble EPUB using EbookLib."""
        from ebooklib import epub

        # Modern ebooklib removed EpubBook.get_type(); EpubWriter still calls it.
        # Re-add a no-op shim so write_epub() succeeds.
        if not hasattr(epub.EpubBook, "get_type"):
            epub.EpubBook.get_type = lambda self: "epub"

        book = epub.EpubBook()
        book.set_identifier(f"fictionzone-{novel_id}")
        book.set_title(info.get("title") or f"Novel {novel_id}")
        book.set_language("en")
        book.add_author(info.get("author") or "Unknown")
        book.add_metadata("DC", "description", info.get("description", ""))

        # Cover
        cover_path = self._find_cover_file(novel_id)
        if cover_path:
            ext = cover_path.suffix.lstrip(".").lower()
            if ext == "jpg":
                ext = "jpeg"
            book.set_cover(f"cover.{ext}", cover_path.read_bytes())

        # Info Page
        genres_str = ", ".join(info.get("genres", []))
        status = info.get("status", "Unknown")
        info_page = epub.EpubHtml(
            title="Book Information",
            file_name="info.xhtml",
            lang="en",
        )
        info_page.content = (
            f"<h1>{html.escape(info.get('title') or 'Novel ' + str(novel_id))}</h1>"
            f"<p><strong>Author:</strong> {html.escape(info.get('author') or 'Unknown')}</p>"
            f"<p><strong>Status:</strong> {html.escape(status)}</p>"
            f"<p><strong>Genres:</strong> {html.escape(genres_str)}</p>"
            f"<h3>Synopsis</h3>"
            f"<div>{paragraphs_to_html(info.get('description', ''))}</div>"
        )
        book.add_item(info_page)
        
        epub_chapters = []
        spine = ["nav", info_page]
        toc = [info_page]

        for chap in chapters:
            c_idx = chap["idx"]
            c_title = chap["title"]
            body_html = paragraphs_to_html(chap["body"])

            chapter = epub.EpubHtml(
                title=c_title,
                file_name=f"chap_{c_idx:04d}.xhtml",
                lang="en",
            )
            chapter.content = (
                f"<h1>{html.escape(c_title)}</h1>\n"
                f"<p><em>Chapter {c_idx}</em></p>\n"
                f"{body_html}"
            )
            book.add_item(chapter)
            epub_chapters.append(chapter)
            toc.append(chapter)
            spine.append(chapter)

        book.toc = toc
        book.spine = spine
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        epub.write_epub(str(out_path), book)
