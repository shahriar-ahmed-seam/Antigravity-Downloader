<div align="center">

# Antigravity Downloader

**A native Android client that pulls novels from fictionzone.net straight off its JSON gateway and assembles them into clean EPUBs — entirely on-device.**

No headless browser. No HTML scraping. Just the same authenticated, AJAX-style API calls the site's own frontend makes — talking directly to the backend.

`Kotlin` · `Jetpack Compose` · `Coroutines` · `WebView transport` · `EPUB3`

</div>

---

## TL;DR for engineers

fictionzone.net is a SPA. Its pages are shells; the actual content is hydrated client-side
via XHR/`fetch` calls to a single internal gateway that returns **structured JSON straight
from their datastore**. Antigravity speaks that protocol directly:

- **We do not parse rendered HTML for content.** Chapters and the chapter index are fetched
  as JSON rows from the gateway — the exact endpoints the website's own JavaScript hits.
- **The only HTML we touch** is the novel landing page, and only to read its embedded
  structured metadata (JSON-LD / Open Graph) to bootstrap the title, cover and `novel_id`.
  Everything after that is API.
- **Auth is a bearer JWT**, carried inside the gateway's inner routing envelope — identical
  to the reference pipeline this app was ported from.

The interesting problem was **transport**, not parsing (see below).

---

## The transport problem (and the fix)

The gateway sits behind **Cloudflare**, which fingerprints the TLS `ClientHello` (JA3/JA4).
A vanilla HTTP client — `OkHttp`, `HttpURLConnection`, Python `requests` — presents a
non-browser fingerprint and gets a hard `403`. The original desktop pipeline worked only
because it used `curl_cffi` to **impersonate Chrome's TLS stack**.

Reproducing TLS impersonation on Android is brittle and a maintenance trap. Instead:

> **Antigravity uses an offscreen `WebView` as its network transport.** All gateway calls are
> issued with `fetch()` from inside the loaded `fictionzone.net` origin, so every request goes
> out through the device's real Chromium network stack.

That buys us, for free and forever:

- a **genuine Chrome TLS fingerprint** (Cloudflare is satisfied),
- correct **same-origin** semantics (`Origin`/`Referer` are real),
- automatic propagation of any **Cloudflare clearance cookies**.

A small `@JavascriptInterface` bridge marshals each response back into a coroutine via a
`CompletableDeferred`, so callers `await` a normal suspend function and never know a WebView
is underneath. It behaves like an HTTP client; it just happens to have Chrome's fingerprint.

---

## The gateway protocol

Every call is one `POST` to:

```
https://fictionzone.net/api/__api_party/fictionzone
```

The body is a **routing envelope** the gateway unpacks server-side. The bearer token rides
in the inner `headers`, not the outer request:

```jsonc
{
  "path": "/platform/chapter-content",
  "method": "GET",
  "query": { "novel_id": "71679", "chapter_id": "6410897", "highlight": false },
  "headers": [
    ["authorization", "Bearer eyJhbGc…"],
    ["x-request-time", "2026-06-29T15:42:11.337Z"]   // regenerated per call
  ]
}
```

Responses are uniform: `{ "success": true, "data": { … }, "code": 0, "message": "ok" }`.

| Endpoint | Purpose | Shape |
|---|---|---|
| `/platform/chapter-lists` | Paginated chapter index | `{ chapters: [{id, title, idx}], total }` |
| `/platform/chapter-content` | One chapter body | `{ id, title, idx, content }` |

The client dedupes the index by `id` (the DB row key — `idx` repeats across pages), then
fetches content rows directly. Structured data in, structured data out.

---

## Download engine

The on-device scraper is a single suspend state machine with a clean control surface:

- **Multi-token rotation.** Register any number of bearer tokens. The engine rotates across
  them and, on a `401` / `"login to continue"` response, **retires the offending token and
  retries the same chapter on the next live one** — no progress lost. If every token dies,
  the job parks in `TOKEN_EXPIRED`, surfaces the Tokens tab, and resumes the instant you add
  a working one.
- **Polite, human-shaped traffic.** Fetch order is **shuffled**, and every request is spaced
  by a **uniform random delay inside a window you set** (`min`/`max` seconds).
- **Idempotent + resume-safe.** Each chapter is cached as a normalized `.txt`; re-runs skip
  what's already on disk unless you force a redownload. Pause / resume / stop at any time.
- **Backpressure on failure.** Consecutive transport errors trip a circuit breaker after a
  bounded number of retries.
- **Foreground service.** The run (and the WebView transport) is hosted in a foreground
  service with a live progress notification, so Android won't reap it mid-download.

On completion it compiles a valid **EPUB3** with a pure `java.util.zip` writer — `mimetype`
stored first, container, OPF manifest/spine, nav, a cover + info page, and one XHTML document
per chapter. No third-party EPUB dependency, no server round-trip.

---

## Architecture

```
ui/  (Compose)        ──observes──▶  DownloadController (StateFlow<DownloadState>, logs)
  AppViewModel                              │ owns the scrape loop, token rotation, flow control
                                            ▼
service/DownloadService  ──hosts──▶  DownloadController.run(config, tokens)
                                            │ uses
        ┌───────────────────────────────────┼───────────────────────────────┐
        ▼                                    ▼                                ▼
core/GatewayEngine            core/NovelCache                      core/EpubBuilder
 (offscreen WebView transport)  (info.json / chapters.json / *.txt)  (zip → EPUB3)
        ▲
core/NovelAnalyzer ─ landing-page metadata bootstrap (JSON-LD/OG)
core/HtmlParser    ─ structured-data extraction (metadata only)
core/TokenStore    ─ DataStore-backed token list + JWT expiry decode
```

```
android/app/src/main/
├── java/com/antigravity/noveldownloader/
│   ├── core/      GatewayEngine · NovelAnalyzer · HtmlParser · NovelCache · EpubBuilder · TokenStore · DownloadController · Models
│   ├── service/   DownloadService (foreground)
│   └── ui/        Compose screens (Download · Console · Library · Tokens), theme, AppViewModel
└── res/           adaptive launcher icons · splash · brand drawables
```

---

## Build

**Requirements:** JDK 17+, Android SDK (platform 35, build-tools 35). Gradle wrapper included.

```bash
cd android
./gradlew assembleDebug      # app/build/outputs/apk/debug/app-debug.apk
./gradlew assembleRelease    # app/build/outputs/apk/release/app-release.apk  (signed if keystore present)
```

Windows: use `gradlew.bat`. `minSdk 26` (Android 8.0+), `targetSdk 35`.

### Signing

Release signing is read from a gitignored `android/keystore.properties`:

```properties
storeFile=keystore/antigravity-release.keystore
storePassword=…
keyAlias=…
keyPassword=…
```

Generate a keystore once:

```bash
keytool -genkeypair -v -keystore android/keystore/antigravity-release.keystore \
  -alias antigravity -keyalg RSA -keysize 2048 -validity 10000
```

If the properties file is absent, the release APK is left unsigned.

### Branding assets

The launcher icon (adaptive, all densities), splash, and in-app logo are generated from the
source art in `android/assets/` (`logo.png`, `splash.png`). Replace those and regenerate the
icons to rebrand.

---

## Using it

1. **Tokens** — paste one or more bearer tokens. Capture from your browser: DevTools →
   Network → any gateway request → Headers → copy the full `authorization` value (with the
   `Bearer ` prefix). Stored only on-device via DataStore.
2. **Download** — paste a `https://fictionzone.net/novel/<slug>` URL → **Analyze** → set the
   chapter range, the random delay window, and options → **Start Download**.
3. **Console** — live progress, per-chapter logs, pause/resume/stop.
4. **Library** — **Save** the EPUB to Downloads or **Share** it to any app.

---

## Reference backend (optional)

The Python pipeline this app was ported from still runs standalone — a FastAPI service and a
CLI, both hitting the same gateway:

```bash
pip install -r requirements.txt     # curl-cffi required (Cloudflare TLS impersonation)
python server/main.py               # web UI at http://127.0.0.1:8000
```

Full protocol notes, data shapes and gotchas live in [`docs/CONTEXT.md`](docs/CONTEXT.md).

---

## Responsible use

For **personal use** with your own account and content you're entitled to read. Keep delays
reasonable, don't hammer the gateway, and don't redistribute scraped content. Respect
fictionzone.net's terms of service. You own how you use this.

## License

[MIT](LICENSE)
