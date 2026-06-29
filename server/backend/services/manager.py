import logging
import queue
import threading
import uuid
from typing import Optional, Dict, Any, Generator

from backend.config import FICTIONZONE_TOKEN
from backend.core.client import FictionZoneClient
from backend.core.cache import CacheManager
from backend.core.scraper import NovelScraper

logger = logging.getLogger("novel_downloader.manager")


class DownloadJob:
    """Represents an active or finished download task."""

    def __init__(self, novel_id: str, scraper: NovelScraper):
        self.job_id = str(uuid.uuid4())
        self.novel_id = novel_id
        self.scraper = scraper
        self.status = "queued"
        self.error: Optional[str] = None
        self.epub_file: Optional[str] = None
        self.logs: list[dict[str, Any]] = []
        self.progress = {
            "total": 0,
            "completed": 0,
            "skipped": 0,
            "percentage": 0.0,
            "current_chapter": ""
        }

        # Thread-safe event queue for Server-Sent Events (SSE)
        self.event_queue: queue.Queue = queue.Queue()
        self.lock = threading.Lock()

    def add_log(self, level: str, message: str, timestamp: float):
        log_entry = {"level": level, "message": message, "timestamp": timestamp}
        with self.lock:
            self.logs.append(log_entry)
        self.event_queue.put({"type": "log", "data": log_entry})

    def update_progress(self, progress_data: dict[str, Any]):
        with self.lock:
            self.progress.update(progress_data)
        self.event_queue.put({"type": "progress", "data": progress_data})

    def update_status(self, status_data: dict[str, Any]):
        with self.lock:
            self.status = status_data["status"]
            if self.status == "completed":
                self.epub_file = status_data.get("epub_file")
            elif self.status == "failed":
                self.error = status_data.get("error")
        self.event_queue.put({"type": "status", "data": status_data})


class DownloadManager:
    """Manages spawning, tracking, and interacting with novel scraper threads."""

    def __init__(self, cache_mgr: CacheManager):
        self.cache = cache_mgr
        self.jobs: Dict[str, DownloadJob] = {}
        self.lock = threading.Lock()

    def start_download(
        self,
        novel_id: str,
        start_chapter: Optional[int] = None,
        end_chapter: Optional[int] = None,
        delay_min: float = 2.0,
        delay_max: float = 6.0,
        force: bool = False,
        highlight: bool = False,
        renumber: bool = False,
        max_failures: int = 5,
        refresh_index: bool = False
    ) -> DownloadJob:
        """Create a client from the .env token, build a scraper, and start the download thread."""
        # Always use the authoritative token from .env
        client = FictionZoneClient(token=FICTIONZONE_TOKEN)

        job_placeholder: list[Optional[DownloadJob]] = [None]

        def scraper_callback(event_type: str, data: dict[str, Any]):
            job = job_placeholder[0]
            if not job:
                return
            if event_type == "log":
                job.add_log(data["level"], data["message"], data["timestamp"])
            elif event_type == "progress":
                job.update_progress(data)
            elif event_type == "status":
                job.update_status(data)

        scraper = NovelScraper(
            novel_id=novel_id,
            client=client,
            cache_mgr=self.cache,
            progress_callback=scraper_callback,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            delay_min=delay_min,
            delay_max=delay_max,
            force=force,
            highlight=highlight,
            renumber=renumber,
            max_failures=max_failures,
            refresh_index=refresh_index
        )

        job = DownloadJob(novel_id, scraper)
        job_placeholder[0] = job

        with self.lock:
            self.jobs[job.job_id] = job

        # Spawn scraper in daemon thread
        t = threading.Thread(target=scraper.run, name=f"scraper-{novel_id}", daemon=True)
        t.start()

        return job

    def get_job(self, job_id: str) -> Optional[DownloadJob]:
        with self.lock:
            return self.jobs.get(job_id)

    def pause_download(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job and job.status == "running":
            job.scraper.pause_event.clear()
            return True
        return False

    def resume_download(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job and job.status in ("paused", "token_expired"):
            job.scraper.pause_event.set()
            return True
        return False

    def abort_download(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job and job.status in ("running", "paused", "token_expired", "queued"):
            job.scraper.abort()
            return True
        return False

    def stream_job_events(self, job_id: str) -> Generator[dict[str, Any], None, None]:
        """Generator that streams events from the queue for Server-Sent Events (SSE).

        First dumps historical state to catch up clients that reload/reconnect.
        """
        job = self.get_job(job_id)
        if not job:
            yield {"type": "error", "message": "Job not found"}
            return

        # 1. Catch up the client with history
        with job.lock:
            yield {"type": "status", "data": {"status": job.status, "epub_file": job.epub_file, "error": job.error}}
            yield {"type": "progress", "data": job.progress}
            for log in job.logs:
                yield {"type": "log", "data": log}

        # 2. Loop and block on new events from the queue
        while True:
            try:
                event = job.event_queue.get(timeout=2.0)
                yield event

                if event["type"] == "status" and event["data"]["status"] in ("completed", "failed", "aborted"):
                    break
            except queue.Empty:
                with job.lock:
                    if job.status in ("completed", "failed", "aborted"):
                        break
                yield {"type": "heartbeat"}
            except GeneratorExit:
                logger.debug(f"SSE client disconnected from job {job_id}")
                break
