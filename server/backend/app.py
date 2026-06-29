import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import BOOKS_DIR, DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, FICTIONZONE_TOKEN
from backend.core.client import FictionZoneClient
from backend.core.cache import CacheManager, safe_filename
from backend.core.parser import parse_novel_html
from backend.core.epub_builder import EpubBuilder
from backend.core.exceptions import TokenExpiredError, NetworkError, BookParseError
from backend.services.manager import DownloadManager

# Setup Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("novel_downloader.api")

# Validate token at startup
if not FICTIONZONE_TOKEN:
    logger.error("FICTIONZONE_TOKEN is not set! Edit .env next to main.py and add your Bearer token.")
else:
    logger.info(f"Token loaded from .env: {FICTIONZONE_TOKEN[:20]}...{FICTIONZONE_TOKEN[-8:]}")

# Initialise App & Services
app = FastAPI(title="Modern Novel Downloader", version="1.0.0")

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cache_mgr = CacheManager(BOOKS_DIR)
download_mgr = DownloadManager(cache_mgr)


def get_client() -> FictionZoneClient:
    """Return a FictionZoneClient wired to the .env token."""
    if not FICTIONZONE_TOKEN:
        raise HTTPException(status_code=500, detail="No FICTIONZONE_TOKEN configured. Edit .env and restart.")
    return FictionZoneClient(token=FICTIONZONE_TOKEN)


# --- Request/Response Models ---

class NovelInfoRequest(BaseModel):
    url: str
    novel_id: Optional[str] = None


class DownloadStartRequest(BaseModel):
    novel_id: str
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None
    delay_min: float = DEFAULT_DELAY_MIN
    delay_max: float = DEFAULT_DELAY_MAX
    force: bool = False
    highlight: bool = False
    renumber: bool = False
    refresh_index: bool = False


class ResumeRequest(BaseModel):
    token: Optional[str] = None


class CompileRequest(BaseModel):
    start_chapter: Optional[int] = None
    end_chapter: Optional[int] = None


# --- API Routes ---

def _decode_jwt_expiry(token: str) -> Optional[int]:
    """Return the exp timestamp from a JWT, or None if undecodable."""
    try:
        clean = token.removeprefix("Bearer ").strip()
        parts = clean.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("exp")
    except Exception:
        return None


@app.get("/api/config")
def get_config():
    """Return current token status so the frontend can display it without exposing the raw token."""
    if not FICTIONZONE_TOKEN:
        return {"token_loaded": False, "token_preview": None, "expires_at": None, "expired": True}

    exp = _decode_jwt_expiry(FICTIONZONE_TOKEN)
    now = time.time()
    expired = (exp is not None and now > exp)

    # Show only first+last chars so the user can verify which token is active
    preview = f"{FICTIONZONE_TOKEN[:24]}...{FICTIONZONE_TOKEN[-8:]}"
    return {
        "token_loaded": True,
        "token_preview": preview,
        "expires_at": exp,
        "expired": expired,
    }


@app.post("/api/check-token")
def check_token():
    """Probe the gateway with the .env token and report whether it is valid."""
    if not FICTIONZONE_TOKEN:
        return {"valid": False, "error": "No token configured in .env"}

    # Local JWT structure + expiry check first
    exp = _decode_jwt_expiry(FICTIONZONE_TOKEN)
    if exp is not None and time.time() > exp:
        return {"valid": False, "error": "Token has expired (local check)."}

    # Live gateway probe: chapter-content is the only endpoint that requires auth
    client = FictionZoneClient(token=FICTIONZONE_TOKEN)
    try:
        res = client.post_gateway(
            "/platform/chapter-content",
            {"novel_id": "1", "chapter_id": "1", "highlight": False}
        )
        msg = res.get("message") or ""
        if "login to continue" in msg.lower():
            return {"valid": False, "error": "Gateway rejected the token — update .env with a fresh token and restart."}
        return {"valid": True, "error": None}
    except TokenExpiredError as err:
        return {"valid": False, "error": str(err)}
    except NetworkError as err:
        return {"valid": False, "error": f"Network error during check: {err}"}
    except Exception as err:
        return {"valid": False, "error": str(err)}


def fetch_full_chapter_index(novel_id: str, client: FictionZoneClient) -> list[dict]:
    collected = []
    seen_ids = set()
    page = 1
    max_pages = 100
    page_size = 200

    while page <= max_pages:
        response = client.post_gateway(
            "/platform/chapter-lists",
            {"novel_id": novel_id, "page": page, "page_size": page_size}
        )
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
            idx = entry.get("idx") or entry.get("order") or entry.get("index") or entry.get("chapter_no") or entry.get("chapter_number")

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

        if new_count == 0 or new_count < len(raw_list):
            break
        page += 1

    # Sort by idx
    collected.sort(key=lambda e: (e["idx"] is None, e["idx"] if e["idx"] is not None else 0, e["id"]))
    if all(e["idx"] is None for e in collected):
        for idx, e in enumerate(collected, start=1):
            e["idx"] = idx

    return collected


@app.post("/api/novel/info")
def get_novel_info(body: NovelInfoRequest):
    """Fetch landing page HTML, parse metadata, fetch canonical chapter index, and return metadata."""
    client = get_client()
    url_str = body.url

    if "fictionzone.net/novel/" not in url_str:
        raise HTTPException(status_code=400, detail="Invalid novel URL. Must contain fictionzone.net/novel/")

    try:
        # 1. Fetch and Parse HTML Page
        html = client.get_html(url_str)
        metadata = parse_novel_html(html, url_str, fallback_novel_id=body.novel_id)
        novel_id = metadata["novel_id"]

        # Save metadata to cache
        cache_mgr.save_book_info(novel_id, metadata)

        # 2. Download cover image if it exists
        cover_url = metadata.get("cover_url")
        if cover_url:
            try:
                cover_data = client.get_bytes(cover_url)
                ext_match = re.search(r"\.([a-zA-Z0-9]{2,5})(?:\?|$)", cover_url)
                ext = ext_match.group(1).lower() if ext_match else "jpg"
                if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
                    ext = "jpg"

                cover_path = cache_mgr.novel_dir(novel_id) / f"cover.{ext}"
                cover_path.write_bytes(cover_data)

                metadata["cover_path"] = str(cover_path.relative_to(BOOKS_DIR))
                cache_mgr.save_book_info(novel_id, metadata)
            except Exception as err:
                logger.warning(f"Failed to cache cover image for novel {novel_id}: {err}")

        # 3. Retrieve Chapter Index
        chapters = cache_mgr.get_chapter_index(novel_id)
        if not chapters:
            try:
                chapters = fetch_full_chapter_index(novel_id, client)
                cache_mgr.save_chapter_index(novel_id, chapters)
            except Exception as err:
                logger.warning(f"Failed to fetch chapter index: {err}")
                chapters = []

        return {
            "novel_id": novel_id,
            "metadata": metadata,
            "total_chapters": len(chapters),
            "chapters": chapters
        }

    except BookParseError as err:
        raise HTTPException(status_code=422, detail=str(err))
    except TokenExpiredError:
        raise HTTPException(status_code=401, detail="Authentication token has expired.")
    except Exception as err:
        logger.exception("Failed to load book metadata:")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {err}")


@app.post("/api/download/start")
def start_download_job(body: DownloadStartRequest):
    """Submit a background downloader execution run."""
    try:
        job = download_mgr.start_download(
            novel_id=body.novel_id,
            start_chapter=body.start_chapter,
            end_chapter=body.end_chapter,
            delay_min=body.delay_min,
            delay_max=body.delay_max,
            force=body.force,
            highlight=body.highlight,
            renumber=body.renumber,
            refresh_index=body.refresh_index
        )
        return {"job_id": job.job_id, "status": job.status}
    except Exception as err:
        logger.exception("Failed to start download job:")
        raise HTTPException(status_code=500, detail=str(err))


@app.get("/api/download/status/{job_id}")
def get_job_status(job_id: str):
    """Retrieve in-memory execution stats for a running task."""
    job = download_mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    with job.lock:
        return {
            "job_id": job.job_id,
            "novel_id": job.novel_id,
            "status": job.status,
            "error": job.error,
            "epub_file": job.epub_file,
            "progress": job.progress
        }


@app.get("/api/download/stream/{job_id}")
def stream_job_progress(job_id: str):
    """SSE endpoint streaming live download state logs & numerical progress."""
    job = download_mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    def event_generator():
        for event in download_mgr.stream_job_events(job_id):
            yield f"event: {event['type']}\ndata: {json.dumps(event.get('data', {}))}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/download/pause/{job_id}")
def pause_job(job_id: str):
    """Pause the downloader loop thread."""
    success = download_mgr.pause_download(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not pause job. Make sure it is currently running.")
    return {"status": "paused"}


@app.post("/api/download/resume/{job_id}")
def resume_job(job_id: str):
    """Resume a paused scraper run."""
    success = download_mgr.resume_download(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not resume job. Make sure it is currently paused.")
    return {"status": "running"}


@app.post("/api/download/abort/{job_id}")
def abort_job(job_id: str):
    """Kill scraper thread and clean up task registry."""
    success = download_mgr.abort_download(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not abort job.")
    return {"status": "aborted"}


# --- Library Routes ---

@app.get("/api/library")
def list_library_books():
    """Retrieve all folders and files inside books/ folder."""
    return cache_mgr.list_books()


@app.post("/api/library/{novel_id}/compile")
def compile_epub(novel_id: str, body: CompileRequest):
    """Manually compile an EPUB from the local filesystem cache folder."""
    try:
        builder = EpubBuilder(cache_mgr)
        out_file = builder.compile(
            novel_id=novel_id,
            range_start=body.start_chapter,
            range_end=body.end_chapter
        )
        return {"status": "completed", "epub_file": out_file.name}
    except Exception as err:
        logger.exception("Manual EPUB compile failed:")
        raise HTTPException(status_code=500, detail=str(err))


@app.get("/api/library/{novel_id}/epub")
def download_epub_file(novel_id: str):
    """Download the final generated EPUB file."""
    info = cache_mgr.get_book_info(novel_id)
    if not info:
        raise HTTPException(status_code=404, detail="Novel metadata not found")

    safe_title = safe_filename(info.get("title", f"Novel {novel_id}"))
    epub_path = cache_mgr.novel_dir(novel_id) / f"{safe_title}.epub"

    if not epub_path.exists():
        c_dir = cache_mgr.chapters_dir(novel_id)
        if c_dir.exists() and len(list(c_dir.glob("*.txt"))) > 0:
            try:
                builder = EpubBuilder(cache_mgr)
                builder.compile(novel_id)
            except Exception as err:
                raise HTTPException(status_code=404, detail=f"EPUB file not found and auto-compile failed: {err}")
        else:
            raise HTTPException(status_code=404, detail="EPUB file not found and no cached chapters available to compile.")

    return FileResponse(
        path=epub_path,
        filename=f"{safe_title}.epub",
        media_type="application/epub+zip"
    )


@app.delete("/api/library/{novel_id}")
def delete_library_book(novel_id: str):
    """Delete a downloaded novel cache and files from storage."""
    success = cache_mgr.delete_book(novel_id)
    if not success:
        raise HTTPException(status_code=404, detail="Novel folder not found.")
    return {"status": "deleted"}


# Mount Frontend static dashboard files
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    logger.warning(f"Frontend static files directory not found at: {frontend_dir}")
