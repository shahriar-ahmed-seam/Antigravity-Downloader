import logging
import random
import threading
import time
from typing import Optional, Callable, Any, Union

from backend.core.client import FictionZoneClient
from backend.core.cache import CacheManager
from backend.core.epub_builder import EpubBuilder
from backend.core.exceptions import TokenExpiredError, NetworkError, ScraperException

logger = logging.getLogger("novel_downloader.scraper")


class NovelScraper:
    """Core novel download workflow runner.

    Designed to execute in a background thread, reporting progress via a callback
    and handling token-related pauses.
    """

    def __init__(
        self,
        novel_id: str,
        client: FictionZoneClient,
        cache_mgr: CacheManager,
        progress_callback: Callable[[str, dict[str, Any]], None],
        start_chapter: Optional[int] = None,
        end_chapter: Optional[int] = None,
        delay_min: float = 2.0,
        delay_max: float = 6.0,
        force: bool = False,
        highlight: bool = False,
        renumber: bool = False,
        max_failures: int = 5,
        refresh_index: bool = False
    ):
        self.novel_id = str(novel_id)
        self.client = client
        self.cache = cache_mgr
        self.progress_cb = progress_callback
        self.start_chapter = start_chapter
        self.end_chapter = end_chapter
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.force = force
        self.highlight = highlight
        self.renumber = renumber
        self.max_failures = max_failures
        self.refresh_index = refresh_index

        # Flow Control Events
        self.pause_event = threading.Event()
        self.pause_event.set()  # Starts as running (True)
        self.token_update_event = threading.Event()
        self.token_required = False
        self.is_aborted = False

        self.consecutive_failures = 0
        self.total_to_fetch = 0
        self.completed_fetches = 0
        self.skipped_fetches = 0

    def log(self, message: str, level: str = "info"):
        """Emit log line to the progress callback."""
        logger.info(f"[{level.upper()}] {message}")
        self.progress_cb("log", {"level": level, "message": message, "timestamp": time.time()})

    def emit_progress(self, current_chap_title: str = ""):
        """Emit numerical progress."""
        total = self.total_to_fetch
        done = self.completed_fetches
        percent = (done / total * 100.0) if total > 0 else 100.0
        self.progress_cb("progress", {
            "total": total,
            "completed": done,
            "skipped": self.skipped_fetches,
            "percentage": round(percent, 1),
            "current_chapter": current_chap_title
        })

    def abort(self):
        """Request the scraper thread to stop execution immediately."""
        self.is_aborted = True
        self.pause_event.set()
        self.token_update_event.set()



    def _ensure_chapter_index(self) -> list[dict[str, Any]]:
        """Fetch the chapter list from the API if missing or force-refreshed."""
        index = self.cache.get_chapter_index(self.novel_id)
        if index and not self.refresh_index:
            return index

        self.log("Fetching chapter list index from FictionZone gateway...")
        
        collected = []
        seen_ids = set()
        page = 1
        max_pages = 100
        page_size = 200

        while page <= max_pages:
            if self.is_aborted:
                return []
            
            try:
                response = self.client.post_gateway(
                    "/platform/chapter-lists",
                    {"novel_id": self.novel_id, "page": page, "page_size": page_size}
                )
            except TokenExpiredError as err:
                # Token expired while trying to get the index.
                # Trigger the token pause protocol
                self.log("Token expired while fetching chapter index. Pausing scraper...", "warn")
                self.token_required = True
                self.progress_cb("status", {"status": "token_expired"})
                
                # Block here until user updates the token
                self.token_update_event.clear()
                self.token_update_event.wait()
                
                if self.is_aborted:
                    return []
                # Retry same page
                continue
            except NetworkError as err:
                raise ScraperException(f"Failed to fetch chapter index: {err}")

            data = response.get("data", {}) or {}
            raw_list = data.get("chapters") or data.get("list") or data.get("items") or []
            if not raw_list and isinstance(data, list):
                raw_list = data
            if not raw_list:
                break

            new_count = 0
            for entry in raw_list:
                cid = entry.get("id") or entry.get("chapter_id") or entry.get("_id")
                title = entry.get("title") or entry.get("name") or ""
                idx = entry.get("idx") or entry.get("order") or entry.get("index") or entry.get("chapter_no")
                
                if cid is None:
                    continue
                try:
                    idx_int = int(idx) if idx is not None else None
                except (TypeError, ValueError):
                    idx_int = None

                normalized_entry = {
                    "id": str(cid),
                    "title": str(title).strip(),
                    "idx": idx_int,
                }

                if normalized_entry["id"] in seen_ids:
                    continue
                seen_ids.add(normalized_entry["id"])
                collected.append(normalized_entry)
                new_count += 1

            self.log(f"Parsed page {page}: +{new_count} chapters (total index size: {len(collected)})")

            total = data.get("total") or data.get("total_count")
            if total is not None:
                try:
                    if len(collected) >= int(total):
                        break
                except (TypeError, ValueError):
                    pass
            if new_count == 0 or new_count < len(raw_list):
                break
            page += 1

        if not collected:
            raise ScraperException("FictionZone returned an empty chapter index.")

        # Sort and assign fallback sequence numbers if idx fields are missing
        collected.sort(key=lambda e: (e["idx"] is None, e["idx"] if e["idx"] is not None else 0, e["id"]))
        if all(e["idx"] is None for e in collected):
            for idx, e in enumerate(collected, start=1):
                e["idx"] = idx

        self.cache.save_chapter_index(self.novel_id, collected)
        return collected

    def run(self):
        """Execute the scrape loop."""
        try:
            self.progress_cb("status", {"status": "running"})
            self.log(f"Starting downloader task for novel ID: {self.novel_id}")
            self.log(f"HTTP Backend: {self.client.backend_name}")

            # 1. Align Chapter Index
            chapters = self._ensure_chapter_index()
            if self.is_aborted:
                self.progress_cb("status", {"status": "aborted"})
                self.log("Task aborted by user.")
                return

            self.log(f"Loaded chapter index containing {len(chapters)} total chapters.")

            # 2. Filter requested ranges
            selected_chapters = []
            for idx, entry in enumerate(chapters, start=1):
                c_idx = entry.get("idx")
                current_idx = c_idx if c_idx is not None else idx
                
                if self.start_chapter is not None and current_idx < self.start_chapter:
                    continue
                if self.end_chapter is not None and current_idx > self.end_chapter:
                    continue
                selected_chapters.append(entry)

            if not selected_chapters:
                self.log("No chapters match the selected start/end range limit.", "error")
                self.progress_cb("status", {"status": "failed", "error": "No chapters in range"})
                return

            self.log(f"Selected range includes {len(selected_chapters)} chapters (from canonical index).")

            # 3. Identify chapters that need to be fetched (respecting local cache)
            pending_chapters = []
            for entry in selected_chapters:
                idx = entry["idx"]
                if self.force or not self.cache.is_chapter_cached(self.novel_id, idx):
                    pending_chapters.append(entry)
                else:
                    self.skipped_fetches += 1

            self.total_to_fetch = len(pending_chapters)
            self.completed_fetches = 0
            
            self.log(f"{self.total_to_fetch} chapters need to be fetched from API ({self.skipped_fetches} loaded from cache).")
            self.emit_progress()

            if self.total_to_fetch == 0:
                self.log("All selected chapters are already cached locally.")
            else:
                # Randomize the fetch order to avoid detection
                self.log("Shuffling the fetch sequence...")
                random.shuffle(pending_chapters)

                # 4. Scrape loop
                idx_counter = 1
                while idx_counter <= len(pending_chapters):
                    if self.is_aborted:
                        self.progress_cb("status", {"status": "aborted"})
                        self.log("Task aborted by user.")
                        return

                    # Pause handling
                    if not self.pause_event.is_set():
                        self.log("Scraper thread paused.")
                        self.progress_cb("status", {"status": "paused"})
                        self.pause_event.wait()
                        if self.is_aborted:
                            continue
                        self.log("Scraper thread resumed.")
                        self.progress_cb("status", {"status": "running"})



                    entry = pending_chapters[idx_counter - 1]
                    c_idx = entry["idx"]
                    c_id = entry["id"]
                    c_title = entry["title"] or f"Chapter {c_idx}"

                    self.log(f"Fetching chapter {idx_counter}/{self.total_to_fetch}: idx={c_idx} [id={c_id}] - {c_title}")

                    try:
                        response = self.client.post_gateway(
                            "/platform/chapter-content",
                            {"novel_id": self.novel_id, "chapter_id": c_id, "highlight": self.highlight}
                        )
                        
                        data_block = response.get("data", {}) or {}
                        raw_content = data_block.get("content", "")
                        
                        # Overwrite index with current iteration sequence position if renumbering is toggled
                        if self.renumber:
                            c_idx = idx_counter

                        # Save text file to disk
                        self.cache.save_chapter_file(
                            novel_id=self.novel_id,
                            idx=c_idx,
                            title=c_title,
                            chapter_id=c_id,
                            raw_content=raw_content,
                            force=True  # Overwrite since we decided to fetch it
                        )
                        
                        self.completed_fetches += 1
                        self.consecutive_failures = 0
                        self.log(f"Successfully saved: idx={c_idx} - {c_title}", "success")
                        self.emit_progress(c_title)

                        # Sleep with jitter between requests (skip after final item)
                        if idx_counter < len(pending_chapters):
                            sleep_dur = random.uniform(self.delay_min, self.delay_max)
                            self.log(f"Sleeping for {sleep_dur:.2f}s...")
                            time.sleep(sleep_dur)

                        idx_counter += 1

                    except TokenExpiredError:
                        raise ScraperException("Token has expired. Update .env with a fresh token and restart.")
                    except NetworkError as err:
                        self.consecutive_failures += 1
                        self.log(f"HTTP/Gateway fetch error: {err} (consecutive failure {self.consecutive_failures}/{self.max_failures})", "warn")
                        
                        if self.consecutive_failures >= self.max_failures:
                            raise ScraperException("Aborted: too many consecutive networking failures.")
                        
                        # Sleep a bit before retrying the same chapter
                        time.sleep(3.0)

            # 5. Compile EPUB automatically upon successful completion!
            self.log("All chapters retrieved. Launching EPUB compiler...")
            builder = EpubBuilder(self.cache)
            # Default compile will aggregate all cached chapters (merging new & old ones)
            out_file = builder.compile(
                novel_id=self.novel_id,
                range_start=self.start_chapter,
                range_end=self.end_chapter
            )
            self.log(f"EPUB successfully compiled: {out_file.name}", "success")
            
            self.progress_cb("status", {"status": "completed", "epub_file": out_file.name})

        except ScraperException as err:
            self.log(f"Scraper process failed: {err}", "error")
            self.progress_cb("status", {"status": "failed", "error": str(err)})
        except Exception as err:
            logger.exception("Unexpected error inside scraping execution thread:")
            self.log(f"Unexpected internal error: {err}", "error")
            self.progress_cb("status", {"status": "failed", "error": str(err)})
