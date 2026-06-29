import json
import re
from typing import Optional, Any
from urllib.parse import urljoin

from backend.core.exceptions import BookParseError

# RegEx patterns for parsing HTML
_META_RE = re.compile(
    r"""<meta\s+[^>]*?(?:name|property)=["']([^"']+)["']\s+[^>]*?content=["']([^"']*)["']""",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_SRC_RE = re.compile(r"""src=["']([^"']+)["']""", re.IGNORECASE)


def parse_meta(html: str) -> dict[str, str]:
    """Pull every <meta name|property=... content=...> tag into a flat dict."""
    out: dict[str, str] = {}
    for key, value in _META_RE.findall(html):
        out[key.lower()] = value
    title_match = _TITLE_RE.search(html)
    if title_match:
        out.setdefault("html:title", title_match.group(1).strip())
    return out


def parse_jsonld(html: str) -> list[dict[str, Any]]:
    """Parse every JSON-LD block, returning dicts only."""
    blocks: list[dict[str, Any]] = []
    for raw in _JSONLD_RE.findall(html):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            # Try to fix common trailing comma issue
            try:
                obj = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except json.JSONDecodeError:
                continue
        if isinstance(obj, dict):
            blocks.append(obj)
        elif isinstance(obj, list):
            blocks.extend(b for b in obj if isinstance(b, dict))
    return blocks


def find_cover_url(html: str, meta: dict[str, str]) -> Optional[str]:
    """Find cover image URL from meta tags or fallback containers."""
    for key in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        if meta.get(key):
            return meta[key]
    
    # Fallback to class="cover" container <img>
    cover_div = re.search(
        r'(?is)<div[^>]*class=["\'][^"\']*cover[^"\']*["\'][^>]*>(.*?)</div>',
        html,
    )
    if cover_div:
        m = _SRC_RE.search(cover_div.group(1))
        if m:
            return m.group(1)
    return None


def find_description(html: str, meta: dict[str, str], jsonld_blocks: list[dict]) -> str:
    """Find book description from JSON-LD or meta tags."""
    for block in jsonld_blocks:
        desc = block.get("description")
        if isinstance(desc, str) and desc.strip():
            return desc.strip()
    for key in ("og:description", "twitter:description", "description"):
        if meta.get(key):
            return meta[key].strip()
    return ""


def find_author(meta: dict[str, str], jsonld_blocks: list[dict]) -> str:
    """Find book author from JSON-LD or meta tags."""
    for block in jsonld_blocks:
        author = block.get("author")
        if isinstance(author, dict):
            name = author.get("name")
            if name:
                return str(name).strip()
        if isinstance(author, str) and author.strip():
            return author.strip()
    return meta.get("author", "").strip() or meta.get("book:author", "").strip() or "Unknown"


def find_genres(html: str, meta: dict[str, str]) -> list[str]:
    """Find book genres from tags meta or class="genre" elements."""
    raw = meta.get("book:tag", "") or meta.get("keywords", "")
    if raw:
        return [t.strip() for t in re.split(r"[,;|]", raw) if t.strip()]
        
    # Inline genre links (fictionzone uses <a class="genre">...)
    matches = re.findall(
        r'(?is)<a[^>]+class=["\'][^"\']*genre[^"\']*["\'][^>]*>([^<]+)</a>',
        html,
    )
    return [m.strip() for m in matches if m.strip()]


def find_novel_id_from_html(html: str) -> Optional[str]:
    """Search for the novel id in inline scripts, queries, attributes, or links."""
    patterns = [
        r'["\']?novel_id["\']?\s*[:=]\s*["\']?(\d+)["\']?',
        r'["\']?novelId["\']?\s*[:=]\s*["\']?(\d+)["\']?',
        r'data-novel-id=["\']?(\d+)["\']?',
        r'novel-id=["\']?(\d+)["\']?',
        r'/novel/[^/]+/(\d+)',
        r'/novel/[^/]+-(\d+)',
        r'chapter-lists.*novel_id=(\d+)',
        r'novel-detail.*novel_id=(\d+)',
        r'["\']?query["\']?\s*:\s*\{\s*["\']?novel_id["\']?\s*:\s*["\']?(\d+)["\']?',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def parse_novel_html(html: str, page_url: str, fallback_novel_id: Optional[str] = None) -> dict[str, Any]:
    """Parse raw novel page HTML and return a normalized dictionary of book metadata.

    Raises:
        BookParseError: if parsing critical info like novel_id fails.
    """
    meta = parse_meta(html)
    jsonld = parse_jsonld(html)

    title = (meta.get("og:title")
             or meta.get("twitter:title")
             or meta.get("html:title")
             or "").strip()
    
    # Strip " - FictionZone" suffix
    title = re.sub(r"\s*[-|–—]\s*FictionZone\s*$", "", title, flags=re.IGNORECASE)
    if not title:
        title = f"Novel {fallback_novel_id}" if fallback_novel_id else "Unknown Novel"

    description = find_description(html, meta, jsonld)
    author = find_author(meta, jsonld)
    cover_url = find_cover_url(html, meta)
    if cover_url:
        cover_url = urljoin(page_url, cover_url)
        
    genres = find_genres(html, meta)
    status = meta.get("book:status", "").strip()
    novel_id = find_novel_id_from_html(html) or fallback_novel_id

    if not novel_id:
        raise BookParseError("Could not determine novel_id from the webpage. Please provide a novel_id manually.")

    return {
        "novel_id": str(novel_id),
        "title": title,
        "author": author,
        "description": description,
        "cover_url": cover_url,
        "status": status,
        "genres": genres,
        "source_url": page_url,
    }
