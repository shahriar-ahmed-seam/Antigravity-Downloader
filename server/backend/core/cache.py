import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Optional, Any, Union

from backend.config import BOOKS_DIR

logger = logging.getLogger("novel_downloader.cache")

_FILENAME_SAFE_RE = re.compile(r"[^\w\-. ]+", re.UNICODE)


def safe_filename(name: str, fallback: str = "untitled") -> str:
    """Return a filename safe for both Windows and POSIX filesystems."""
    if not name:
        return fallback
    # Normalize unicode and strip control chars
    cleaned = unicodedata.normalize("NFKC", name).strip()
    cleaned = "".join(ch for ch in cleaned if ch.isprintable() and ch not in "\r\n\t")
    cleaned = _FILENAME_SAFE_RE.sub("_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    if not cleaned or len(cleaned) > 200:
        return fallback
    return cleaned


class CacheManager:
    """Manages reading and writing novel data to the local books directory."""

    def __init__(self, books_dir: Path = BOOKS_DIR):
        self.books_dir = Path(books_dir)
        self.books_dir.mkdir(parents=True, exist_ok=True)

    def novel_dir(self, novel_id: Union[str, int]) -> Path:
        """Get and ensure the book directory exists."""
        path = self.books_dir / str(novel_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def chapters_dir(self, novel_id: Union[str, int]) -> Path:
        """Get and ensure the chapters subdirectory exists."""
        path = self.novel_dir(novel_id) / "chapters"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_book_info(self, novel_id: Union[str, int], info: dict[str, Any]) -> Path:
        """Save the book metadata to info.json."""
        path = self.novel_dir(novel_id) / "info.json"
        # Standardize relative cover path if cover was downloaded
        path.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def get_book_info(self, novel_id: Union[str, int]) -> Optional[dict[str, Any]]:
        """Retrieve the cached book metadata if available."""
        path = self.novel_dir(novel_id) / "info.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError) as err:
                logger.error(f"Error reading info.json for book {novel_id}: {err}")
        return None

    def save_chapter_index(self, novel_id: Union[str, int], chapters: list[dict[str, Any]]) -> Path:
        """Save the canonical list of chapters to chapters.json."""
        path = self.novel_dir(novel_id) / "chapters.json"
        payload = {
            "novel_id": str(novel_id),
            "count": len(chapters),
            "chapters": chapters,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def get_chapter_index(self, novel_id: Union[str, int]) -> Optional[list[dict[str, Any]]]:
        """Retrieve the cached chapter list if available."""
        path = self.novel_dir(novel_id) / "chapters.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get("chapters", [])
            except (json.JSONDecodeError, IOError) as err:
                logger.error(f"Error reading chapters.json for book {novel_id}: {err}")
        return None

    def is_chapter_cached(self, novel_id: Union[str, int], idx: int) -> bool:
        """Check if a chapter text file already exists on disk for the given idx."""
        c_dir = self.chapters_dir(novel_id)
        # Search for files matching '0001 - *.txt'
        matches = list(c_dir.glob(f"{int(idx):04d} - *.txt"))
        return len(matches) > 0

    def normalize_text(self, raw: str) -> str:
        """Verbatim text retention with normalized spacing and line endings."""
        if not raw:
            return ""
        # 1. Normalise line endings
        text = raw.replace("\r\n", "\n").replace("\r", "\n")
        # 2. Strip trailing whitespace from each line
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        # 3. Collapse 3+ consecutive blank lines down to exactly 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip("\n") + "\n"

    def build_banner(self, novel_id: str, idx: int, title: str, chapter_id: str, content_len: int) -> str:
        """Build the metadata banner prefixed at the top of each chapter txt file."""
        width = max(40, len(title) + 16)
        bar = "=" * width
        return (
            f"{bar}\n"
            f"  {title}\n"
            f"  Chapter {idx}\n"
            f"{bar}\n"
            f"  novel_id:   {novel_id}\n"
            f"  chapter_id: {chapter_id}\n"
            f"  characters: {content_len}\n"
            f"{bar}\n\n"
        )

    def save_chapter_file(self, novel_id: Union[str, int], idx: int, title: str,
                          chapter_id: str, raw_content: str, force: bool = False) -> Path:
        """Normalize and write chapter content to books/<novel_id>/chapters/<idx:04d> - <title>.txt."""
        c_dir = self.chapters_dir(novel_id)
        safe_title = safe_filename(title, fallback="Untitled")
        file_path = c_dir / f"{int(idx):04d} - {safe_title}.txt"

        if file_path.exists() and not force:
            return file_path

        normalized = self.normalize_text(raw_content)
        
        # Clean text format: Title on first line, followed by empty line, then content
        clean_content = f"{title}\n\n{normalized}"
        
        file_path.write_text(clean_content, encoding="utf-8")
        return file_path
        
    def list_books(self) -> list[dict[str, Any]]:
        """List all books found in the books directory with metadata & download status."""
        books = []
        if not self.books_dir.exists():
            return books

        for p in self.books_dir.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                novel_id = p.name
                info = self.get_book_info(novel_id)
                chapters_idx = self.get_chapter_index(novel_id)
                
                # Check how many chapter text files are downloaded
                downloaded_count = 0
                c_dir = p / "chapters"
                if c_dir.exists():
                    downloaded_count = len(list(c_dir.glob("*.txt")))

                # Find any generated EPUB
                epub_path = None
                epubs = list(p.glob("*.epub"))
                if epubs:
                    epub_path = epubs[0].name
                
                # If no metadata exists, fill with default placeholders
                if not info:
                    info = {
                        "novel_id": novel_id,
                        "title": f"Novel {novel_id}",
                        "author": "Unknown",
                        "description": "No metadata downloaded.",
                        "status": "",
                        "genres": [],
                    }
                
                books.append({
                    "novel_id": novel_id,
                    "metadata": info,
                    "total_chapters": len(chapters_idx) if chapters_idx else 0,
                    "downloaded_chapters": downloaded_count,
                    "epub_filename": epub_path,
                    "last_modified": p.stat().st_mtime
                })
        return sorted(books, key=lambda b: b["last_modified"], reverse=True)
        
    def delete_book(self, novel_id: Union[str, int]) -> bool:
        """Safely delete all directories and files for a novel."""
        import shutil
        dir_path = self.novel_dir(novel_id)
        if dir_path.exists():
            shutil.rmtree(dir_path)
            return True
        return False
