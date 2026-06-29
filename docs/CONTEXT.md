# CONTEXT.md — fictionzone.net Novel Downloader + Upcoming Frontend

> **Purpose of this file:** give any new contributor (human or AI) a complete
> picture of the project, the pipeline, the auth model, the data shapes, the
> known gotchas, and the frontend that is about to be built on top of it.
>
> If you only read one file in this repo, read this one.

---

## 1. What this project does

A small Python pipeline that turns a `fictionzone.net` novel URL into a clean
`.epub` file by scraping the site's internal gateway API.

It runs in 4 logical steps:

1. **Book info** — `GET /novel/<slug>` → `info.json` + `cover.<ext>`
2. **Chapter index** — paginated `POST /platform/chapter-lists` → `chapters.json`
3. **Chapter content** — per-chapter `POST /platform/chapter-content` →
   `chapters/<idx:04d> - <title>.txt` (one file per chapter)
4. **EPUB** — all `.txt` files → `<title>.epub`

Everything is driven from a `novel_id` (e.g. `27413`) and the resulting files
all live under `books/<novel_id>/`.

A **web frontend** is being added on top of this. The user will paste a
fictionzone novel frontpage URL into a form, the app extracts the slug + id,
runs the pipeline in the background, shows progress, and serves the resulting
EPUB as a download. There is also a **manual token input** because the
captured JWT expires (every 24 h – 7 d depending on FictionZone's policy) and
the user has to refresh it from their browser.

---

## 2. Repo layout

```
.
├── books/                  ← output: one folder per novel
│   └── <novel_id>/
│       ├── info.json
│       ├── cover.<ext>
│       ├── chapters.json
│       ├── chapters/<idx:04d> - <title>.txt
│       └── <title>.epub
├── scripts/                ← the pipeline (all CLI scripts, importable as modules)
│   ├── common.py           ← shared config + HTTP helpers (THE auth lives here)
│   ├── fetch_book_info.py  ← step 1: GET the /novel/<slug> HTML page
│   ├── fetch_chapter_list.py ← step 2: paginated chapter index
│   ├── fetch_chapter.py    ← debugging: one-shot chapter POST
│   ├── save_chapter.py     ← library: gateway response → normalised .txt
│   ├── scrape_novel.py     ← step 3: orchestrator with random delays
│   └── compile_epub.py     ← step 4: chapters/*.txt → .epub
├── testing/                ← experiments only (excluded from the pipeline)
├── requirements.txt
├── README.md               ← user-facing CLI docs
└── CONTEXT.md              ← this file
```

The scripts are written to be **importable as modules** as well as runnable
as CLIs. Each `import common` does `sys.path.insert(0, parent_of_common)`
so they can be invoked from the repo root without packaging. A future
Python package wrapper may add a real `pyproject.toml`.

---

## 3. The auth model — **read this before touching the frontend**

The site is gated by a JWT in the form `Bearer <token>`. Captured tokens
have a lifetime identical to the user's login session. The user has
reported that **tokens expire every 24 hours to 7 days** — the exact window
is not predictable, you have to assume "stale at any moment" and design
around it.

### Where the token lives today

- A hard-coded `AUTH_TOKEN` constant in `scripts/common.py` (top of file,
  currently `Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`).
- It's injected into the **inner** POST body as an `authorization` header
  inside the routing envelope (see §4). The **outer** POST uses public
  browser-style headers and does NOT carry the token.
- The token is **never** sent to the public `fictionzone.net` HTML
  endpoints — those work with cookie-based session auth from a real
  browser, but the gateway uses JWT only.

### How the frontend will work with the token

The user wants to **manually paste the token** in a UI field because the
captured one keeps expiring. Design implications:

- The token must be **pluggable** at runtime — not a frozen constant.
- Pipeline functions must accept a `token: str` (or pull it from a config
  object) rather than importing `common.AUTH_TOKEN` directly.
- When the gateway returns **401 Unauthorized**, the frontend should:
  1. Stop the run,
  2. Show a clear "token expired, paste a new one" message,
  3. Resume / restart the run with the new token once the user submits it.
- A small token-validity probe (e.g. a cheap call to
  `/platform/chapter-lists?novel_id=1&page=1&page_size=1`) is worth having
  so the UI can show "this token looks dead" proactively.
- The token is a **secret** — store it in the frontend's session/local
  storage, never in plain git-tracked files, never in URL params, and never
  log the body of any gateway response to a place the user can see in
  plaintext (the response body itself is fine; it doesn't echo the token).

### How a user captures a new token

In Chrome DevTools → Network tab → click any gateway request → Headers →
copy the `authorization` header value (including the `Bearer ` prefix).
That's the full string to paste.

### Suggested refactor for the frontend

When the frontend is wired up, add a `Token` dataclass to `common.py`:

```python
@dataclass
class Token:
    raw: str            # the "Bearer eyJ..." string the user pastes
    source: str         # "user" | "env" | "default"
    captured_at: datetime
```

and route it through every `post_gateway*` call. The hard-coded
`AUTH_TOKEN` becomes a *fallback* used only when running scripts in dev
without a frontend.

---

## 4. The gateway — single endpoint, two halves

Every API call (chapter list, chapter content, etc.) is a single
**outer POST** to:

```
https://fictionzone.net/api/__api_party/fictionzone
```

The body is a **routing envelope** that gets split server-side. The
envelope tells the gateway *which internal path* to call, with what
method/query/headers, on the user's behalf.

### Outer request (what the script sends)

- **Method:** `POST`
- **URL:** `https://fictionzone.net/api/__api_party/fictionzone`
- **Headers:** `OUTER_HEADERS` in `common.py` — a fixed set of
  Chrome-149 headers (`user-agent`, `sec-ch-ua`, `origin`,
  `referer`, `accept: application/json`, etc.). No `authorization` here.
- **Body (JSON):** a routing envelope (see below).

### Inner routing envelope (the JSON body)

```json
{
  "path": "/platform/chapter-content",
  "method": "GET",
  "query": { "novel_id": "27413", "chapter_id": "1806738", "highlight": false },
  "headers": [
    ["authorization", "Bearer eyJhbGc..."],
    ["x-request-time", "2026-06-25T18:42:11.337Z"]
  ]
}
```

Notes:

- The inner `headers` are forwarded as-is by the gateway. **This is where
  the JWT goes.**
- `x-request-time` is regenerated on every call by `common.build_inner_payload()`
  using `common.now_iso()` (millisecond-precision UTC).
- The inner `method` is almost always `"GET"`, even though the outer is
  `POST`. Don't change it.
- The inner `query` shape differs per endpoint (see §5).

### Response envelope

Every successful response has the shape:

```json
{
  "success": true,
  "data": { ...endpoint-specific... },
  "code": 0,
  "message": "ok"
}
```

`common.post_gateway_safe()` already wraps this: on failure it returns
`{"success": false, "error": "...", "status_code": 401, "cf_ray": "..."}`
instead of raising. Always use the `_safe` variant in long-running
orchestrators like `scrape_novel.py`.

### Cloudflare

The site is behind Cloudflare. Plain `requests` is **banned with 403**
because the TLS fingerprint isn't Chrome-shaped. `common.py` tries to
import `curl_cffi.requests` first and falls back to `requests` if it's
missing. With `curl_cffi`, it sets `impersonate="chrome120"` to match a
real Chrome 120. If Cloudflare updates its fingerprints and you start
seeing 403s again, bump the `impersonate` value to a newer browser.

---

## 5. Endpoint reference

All three endpoints use the same outer POST + inner envelope pattern.

### 5.1 `GET /novel/<slug>` (book info)

- **Type:** direct page fetch, not via the gateway.
- **Helper:** `common.get_html(url)` — sends a `GET` with `HTML_HEADERS`
  (Chrome UA + browser-like `accept`).
- **Input:** the public URL `https://fictionzone.net/novel/<slug>`.
- **Output:** raw HTML. The script `fetch_book_info.py` extracts
  title/author/description/cover/genres via:
  1. JSON-LD `<script type="application/ld+json">` blocks (preferred),
  2. Open Graph + Twitter meta tags,
  3. Inline HTML fallbacks (e.g. `<a class="genre">` for genres).
- The novel id is usually embedded in the page; if not, pass
  `--novel-id` to override.

### 5.2 `POST /platform/chapter-lists` (chapter index)

- **Inner path:** `/platform/chapter-lists`
- **Inner query:**
  ```json
  { "novel_id": "27413", "page": 1, "page_size": 200 }
  ```
- **Inner response data shape:**
  ```json
  {
    "chapters": [
      { "id": "1806484", "title": "Chapter 1", "idx": 1 },
      ...
    ],
    "total": 255
  }
  ```
  (sometimes the server returns `list` or `items` instead of `chapters` —
  the normaliser in `fetch_chapter_list.py` accepts all three).
- **Paging:** `fetch_all()` walks `page=1, 2, 3, ...` until either
  `len(collected) >= total` or a page returns 0 new entries.
  The current `page_size` default is 200.
- **Normalised per entry:** `{ "id": str, "title": str, "idx": int|null }`.
  Saved to `books/<novel_id>/chapters.json` as
  `{ "novel_id": "...", "count": N, "chapters": [...] }`.

### 5.3 `POST /platform/chapter-content` (chapter body)

- **Inner path:** `/platform/chapter-content`
- **Inner query:**
  ```json
  { "novel_id": "27413", "chapter_id": "1806484", "highlight": false }
  ```
  (`highlight` is a boolean; pass `true` to match the browser default and
  get the highlighted variant, which the site uses for some novels.)
- **Inner response data shape:**
  ```json
  {
    "id": "1806484",
    "title": "Chapter 1",
    "idx": 1,
    "content": "Full chapter text here, paragraphs separated by \\n\\n..."
  }
  ```
- **Storage:** `save_chapter.save_chapter()` writes a `.txt` to
  `books/<novel_id>/chapters/<idx:04d> - <safe_title>.txt` with a banner
  header (see §6).
- **Idempotency:** if the file already exists, `save_chapter` is a no-op
  unless `force=True` is passed. This is what makes
  `scrape_novel.py` resume-safe.

### 5.4 Endpoints NOT yet used but worth knowing about

These have been observed in browser traffic and are candidates for
future features (e.g. user library, ratings):

- `/platform/novel-detail?novel_id=...` — richer metadata than the HTML
  page (chapters, status, ratings).
- `/platform/chapter-lists` already covers our needs for the index.

---

## 6. On-disk layout — `books/<novel_id>/`

### `info.json`

```json
{
  "novel_id": "27413",
  "title": "The Destiny",
  "author": "",
  "description": "Qin Zhengxiong traveled to a parallel world ...",
  "cover_url": "https://cdn.fictionzone.net/.../cover.webp",
  "status": "",
  "genres": [ "Action", "Adventure", "Fantasy" ],
  "source_url": "https://fictionzone.net/novel/the-destiny-...",
  "cover_path": "27413\\cover.webp"
}
```

- `cover_path` is **relative to `books/`** (Windows-style backslashes
  on this OS). `compile_epub.py` resolves it via
  `common.BOOKS_ROOT / cover_path`.
- `author` is often empty if FictionZone's page doesn't expose it in
  JSON-LD or any meta tag — non-fatal, the EPUB just shows "Unknown".

### `cover.<ext>`

Binary, `<ext>` is one of `jpg / jpeg / png / webp / gif`. The
extension is preserved from the URL.

### `chapters.json`

```json
{
  "novel_id": "27413",
  "count": 255,
  "chapters": [
    { "id": "1806484", "title": "Chapter 1", "idx": 1 },
    { "id": "1806485", "title": "Chapter 2 ...", "idx": 2 },
    ...
  ]
}
```

**Gotcha — duplicate idx values across pages:** the gateway paginates
by *page size*, not by *new chapters*. With `page_size=200` against a
255-chapter novel, page 1 returns idx 1-200, page 2 returns idx 1-200
*plus* idx 201-255. So `chapters.json` ends up with 255 entries but
only 200 unique `idx` values. The fetch dedupes by `id`, not by `idx`,
because the `id` is the source of truth (it's the database row id).
Downstream code that joins on `idx` (like `compile_epub.py`) must
dedup-by-idx again before iterating.

### `chapters/<idx:04d> - <safe_title>.txt`

Format:

```
========================================
  Chapter 1
  Chapter 1
========================================
  novel_id:   27413
  chapter_id: 1806484
  characters: 6763
========================================

Dragon Kingdom, the ancestral residence of the Qin family in the capital.
...

```

- Banner is **at the top**, not the bottom.
- `<safe_title>` is run through `common.safe_filename()` which NFKC-
  normalises, strips control chars, and replaces `[^\w\-. ]+` with `_`.
- Body text is 100% preserved: only `\r\n → \n` and trailing-whitespace
  stripping are done. Triple+ blank lines collapse to exactly two.
- The banner is what `compile_epub.py` parses via `_split_banner()` to
  extract the chapter title; if you change the banner format, update
  the `BANNER_RE` regex in `compile_epub.py` to match.

### `<title>.epub`

A valid EPUB3 zip with at least:

- `mimetype` (first entry, stored uncompressed — EPUB spec requires it)
- `META-INF/container.xml`
- `OEBPS/content.opf` (manifest + spine)
- `OEBPS/nav.xhtml` (table of contents)
- `OEBPS/chap####.xhtml` (one per chapter)
- `OEBPS/cover.<ext>` (if a cover was downloaded)

Built with `EbookLib` if available, otherwise a hand-rolled
`zipfile` fallback (a single `ZipFile` in `"w"` mode with per-entry
`ZipInfo.compress_type`).

---

## 7. Pipeline orchestration (CLI, today)

```powershell
# 1. Book info + cover
python scripts/fetch_book_info.py `
  "https://fictionzone.net/novel/the-destiny-..." `
  --novel-id 27413

# 2. Chapter index
python scripts/fetch_chapter_list.py 27413

# 3. Scrape (with jitter, resume-aware, --renumber fixes broken server idx)
python scripts/scrape_novel.py 27413 `
  --delay-min 3 --delay-max 8 `
  --start 1 --end 100 `
  --max-failures 5 `
  --renumber

# 4. Compile
python scripts/compile_epub.py 27413
```

Every step is idempotent — re-running picks up where it stopped. Pass
`--force` to `scrape_novel.py` to redownload; pass `--refresh-index`
to discard `chapters.json` and refetch.

---

## 8. Known quirks and gotchas (please read before changing anything)

1. **Cloudflare 403.** Plain `requests` doesn't bypass it. Always rely
   on `curl_cffi` with `impersonate="chrome120"`. The fallback to plain
   `requests` is for offline tests only.

2. **PowerShell + Unicode.** Windows PowerShell 5.1 is cp1252; printing
   `\u2192` or CJK to the console raises `UnicodeEncodeError`. Two fixes:
   - Set `$env:PYTHONIOENCODING = "utf-8"` before running scripts, and
   - Avoid non-ASCII characters in any `print()` in the pipeline code
     (we replaced `→` with `->` in source). The chapter content itself
     is UTF-8 on disk and that's fine.

3. **Token expiry.** See §3. The frontend must let the user paste a
   fresh token, and the pipeline must surface 401s cleanly.

4. **Duplicate `idx` in `chapters.json`.** See §6 / "Gotcha". Always
   dedup by `id` first (fetch does this), then by `idx` at every join
   site.

5. **Server `idx` is unreliable for cross-page novels.** Some pages
   return `idx=1` again on page 2. `scrape_novel.py --renumber` writes
   the file as `<array_position>:04d` so output sorts 0001..0255
   regardless of the server's idea. Use this flag whenever the index
   looks broken.

6. **`EbookLib` ≥ 0.18 removed `EpubBook.get_type()`.** `compile_epub.py`
   monkey-patches a no-op shim. If you upgrade EbookLib, the shim
   becomes a no-op `hasattr` check (it's already guarded).

7. **Modern EbookLib also crashes on `add_metadata("DC", "description", "")`**
   with `TypeError: Argument must be bytes or unicode, got 'NoneType'`.
   The fallback `zipfile` path in `compile_epub.py` is what actually
   produces the EPUB on this machine. Pass `--no-ebooklib` to force it.

8. **`run_in_terminal` background mode in VS Code can be flaky** for
   long-running scrapes. The proven pattern is to run the scraper in
   the foreground (it's idempotent and resume-safe) with `--max N` to
   bound the run length per invocation.

9. **Cover file extension.** The cover URL's extension is preserved
   as-is from the CDN. `cover.webp` is common; some readers won't
   display it. If that's a problem, add a Pillow-based conversion step
   to `download_cover()` in `fetch_book_info.py`.

10. **Author / status are often empty.** Non-fatal. The EPUB
    substitutes "Unknown" for the author.

---

## 9. Planned frontend — what the next agent should build

The user is about to add a web frontend. The minimal viable spec is:

### 9.1 Pages / panels

1. **Home — "New run" form**
   - One text input: `Novel URL` (e.g.
     `https://fictionzone.net/novel/the-destiny-...`).
   - One text input: `JWT token` (pre-filled with the last used one
     if the backend stores it; otherwise blank).
   - Optional: a small "Test token" button that pings
     `/platform/chapter-lists` with a dummy novel id and shows ✅/❌.
   - One button: `Start download`.
   - On submit, the backend:
     a. Parses the URL → extracts slug + tries to derive `novel_id`
        from the HTML, falling back to a hard-coded map or asking the
        user.
     b. Writes the new token to `common.AUTH_TOKEN` (or a `Token`
        object — see §3 refactor) and persists it to a config file.
     c. Launches the 4 pipeline steps as a background job.

2. **Library — past runs**
   - List of `books/<novel_id>/` directories with title, cover thumb,
     chapter count, last-modified time.
   - Per-row buttons: `Download EPUB`, `Re-compile EPUB`,
     `Re-scrape missing chapters`, `Delete`.

3. **Run detail / progress view**
   - Live log tail from the background job (SSE or polling).
   - Chapter count progress: "127 / 255 downloaded, ETA 6m".
   - A "Token expired" banner with a re-paste field if the job hits
     a 401.

### 9.2 Backend shape (suggested)

- **Stack:** FastAPI is the obvious pick (Python, async, easy SSE).
- **Routes:**
  - `POST /api/runs` body `{url, token}` → `{run_id}` (returns 202)
  - `GET /api/runs/{run_id}` → `{status, log_tail, progress, ...}`
  - `GET /api/runs/{run_id}/stream` (SSE)
  - `GET /api/library` → `[{novel_id, title, ...}, ...]`
  - `GET /api/library/{novel_id}/epub` (file download)
  - `POST /api/token` body `{token}` → `{ok}` (validates + persists)
- **Run model:**
  ```python
  @dataclass
  class Run:
      run_id: str
      novel_id: str
      url: str
      token: str
      status: Literal["queued","running","done","failed","token_expired"]
      log: list[str]
      progress: tuple[int,int] | None  # (done, total)
      started_at: datetime
      finished_at: datetime | None
  ```
- **Persistence:** SQLite via `sqlite3` is enough at this scale; one
  table per entity (runs, novels, tokens).

### 9.3 Frontend stack (open to choice)

Pick whatever the user wants — but if there's no strong preference,
the lightest setup is:

- **Backend:** FastAPI + uvicorn + sqlite3
- **Frontend:** plain HTML + a tiny JS file using `fetch` + SSE, or
  React if the user prefers SPA. Server-rendered Jinja templates are
  the smallest dependency.

### 9.4 Refactor checklist before wiring the frontend

- [ ] `common.AUTH_TOKEN` → mutable `Token` object (see §3).
- [ ] All `post_gateway*` calls accept an optional `token` override.
- [ ] Add `python -m fictionzone_dl.cli <subcommand>` entry points
      so the frontend can `subprocess.run` them without spawning
      `python scripts/...py` strings.
- [ ] Optional: a thin Python wrapper `Pipeline.run(novel_id, token)`
      that does steps 1-4 in order and yields progress events; the
      frontend's `POST /api/runs` handler calls this.

---

## 10. Glossary

- **Novel id** — FictionZone's database id for a novel, used as the
  folder name under `books/`. e.g. `27413`.
- **Slug** — URL-friendly name, e.g.
  `the-destiny-s-ultimate-villain-starting-from-killing-the-protagonist`.
  Appears in `/novel/<slug>`.
- **Chapter id** — FictionZone's database id for a chapter, distinct
  from the displayed chapter number. e.g. `1806484`.
- **idx** — the chapter's *display* number inside its novel. The
  server's value is sometimes wrong across pages; the file naming
  uses `--renumber` to overwrite it.
- **Inner path / inner query / inner headers** — fields of the
  routing envelope in the outer POST body. See §4.
- **Outer POST** — the single HTTP request to the gateway URL.
- **Token / JWT** — the `Bearer eyJ...` string captured from a real
  browser session. 24 h – 7 d lifetime.

---

## 11. Quick orientation for an AI agent

If you are reading this to take over the project:

1. **Don't touch `common.AUTH_TOKEN`'s shape** until you do the
   `Token` refactor in §3. The string in there is a real, currently-
   working JWT for the user's own account.
2. **Don't replace `curl_cffi` with `requests`**. Cloudflare will 403
   you within a few requests.
3. **Don't change the banner format** in `save_chapter.py` without
   also updating `BANNER_RE` in `compile_epub.py`.
4. **The zipfile fallback in `compile_epub.py` is the actually-working
   path** on this machine. `EbookLib` crashes with the description
   metadata; the shim + try/except in `main()` already routes to
   the fallback. If you "fix" ebooklib and it suddenly starts being
   used, the output EPUB will be broken again — test the ebooklib
   path explicitly before removing the fallback.
5. **The user's `novel_id` is the primary key** for everything
   filesystem-side. Don't try to use the slug as a folder name;
   slugs collide.
6. **All scripts can be imported as modules** — `from scripts.common
   import post_gateway_safe` etc. Use this from the FastAPI backend,
   don't shell out to `python scripts/...`.
