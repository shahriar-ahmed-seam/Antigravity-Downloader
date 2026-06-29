<div align="center">

# Antigravity — Novel Downloader

**A native Android app that scrapes novels from fictionzone.net and compiles them into clean EPUB files — entirely on-device.**

Multi-token rotation · randomized fetch order · configurable delay windows · offline library · one-tap EPUB export.

</div>

---

## Why this exists

fictionzone.net serves its content through an internal gateway API that is fronted by
**Cloudflare**. Cloudflare fingerprints the TLS handshake, so an ordinary HTTP client is
rejected with `403 Forbidden`. The original desktop pipeline solved this with
[`curl_cffi`](https://github.com/lexiforest/curl_cffi), which impersonates Chrome's TLS
fingerprint.

Reproducing TLS impersonation on Android is fragile. Instead, **Antigravity uses an
offscreen `WebView` as its network engine.** Requests are issued with `fetch()` from inside
the loaded fictionzone.net page, so they run through the device's real Chromium network
stack — a genuine Chrome TLS fingerprint, correct same-origin headers, and any Cloudflare
clearance cookies, all for free. This mirrors the proven pipeline exactly, without
re-implementing TLS.

> The bearer (JWT) token is the only credential you supply. It is placed inside the
> gateway's inner routing envelope, just like the reference implementation.

---

## Features

- **Bring your own tokens.** Add as many bearer tokens as you like. The downloader rotates
  across them and automatically retires any the gateway rejects (401 / "login to continue"),
  rotating to the next live token without losing progress.
- **Human-like traffic.** Fetch order is shuffled and every request is separated by a
  **random delay inside a window you define** (min / max seconds).
- **Resume-safe caching.** Chapters are cached as text files; re-running skips what's already
  on disk. Pause, resume, or stop at any time.
- **On-device EPUB build.** A pure-zip EPUB3 builder (cover, info page, navigation, one
  document per chapter) — no server round-trip.
- **Offline library.** Browse downloaded novels, recompile a range, export to Downloads, or
  share the EPUB to any app.
- **Deliberate UI.** Dark, sharp-edged (zero rounded corners), considered spacing, and a
  customizable hero banner.

---

## Flow

```
Tokens ──▶ Download (URL → Analyze → range + delay) ──▶ Console (live progress + logs) ──▶ Library (export / share)
```

A foreground service keeps the run (and the WebView engine) alive while you're in other
apps, with a progress notification you can stop from the shade.

---

## Repository layout

```
.
├── android/        # The Android app — Kotlin + Jetpack Compose (primary deliverable)
│   └── app/src/main/
│       ├── java/com/antigravity/noveldownloader/
│       │   ├── core/        # engine, parser, cache, scraper, epub builder, tokens
│       │   ├── service/     # foreground download service
│       │   └── ui/          # Compose screens, theme, view model
│       └── assets/          # drop your hero.jpg/png/webp here
├── server/         # Reference FastAPI web app + Python pipeline (the proven backend)
├── scripts/        # Original command-line pipeline (legacy reference)
├── docs/
│   └── CONTEXT.md  # Deep-dive on the gateway, auth model, data shapes and gotchas
└── README.md
```

The `android/` app is a faithful, self-contained port of the logic documented in
[`docs/CONTEXT.md`](docs/CONTEXT.md). The `server/` and `scripts/` trees are kept as the
reference implementations the app was derived from.

---

## Build the app

**Requirements:** JDK 17+, Android SDK (platform 35, build-tools 35), and the Android
`ANDROID_HOME`/SDK configured. A Gradle wrapper is included.

```bash
cd android

# Debug build
./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk

# Signed release build (see "Signing" below)
./gradlew assembleRelease
# → app/build/outputs/apk/release/app-release.apk
```

On Windows use `gradlew.bat`.

### Signing

Release signing is read from a gitignored `android/keystore.properties`:

```properties
storeFile=keystore/antigravity-release.keystore
storePassword=your-store-password
keyAlias=your-alias
keyPassword=your-key-password
```

Generate a keystore once:

```bash
keytool -genkeypair -v -keystore android/keystore/antigravity-release.keystore \
  -alias antigravity -keyalg RSA -keysize 2048 -validity 10000
```

If `keystore.properties` is absent, the release build is left unsigned.

### Hero image

Drop your banner art into `android/app/src/main/assets/` as `hero.jpg`, `hero.png`, or
`hero.webp`. If none is present the app falls back to an indigo gradient banner.
Recommended size: **1080 × 540** (landscape, dark enough for white text to read).

---

## Using the app

1. **Tokens tab** — paste a bearer token. Capture one from your browser: DevTools → Network
   → any gateway request → Headers → copy the full `authorization` value (including the
   `Bearer ` prefix). Add as many as you want.
2. **Download tab** — paste a `https://fictionzone.net/novel/<slug>` URL and tap **Analyze**.
   Set the chapter range, the random delay window, and any options.
3. **Start Download** — watch live progress and logs in the **Console** tab.
4. **Library tab** — **Save** the EPUB to Downloads or **Share** it anywhere.

If every token expires mid-run, the job pauses and jumps you to the Tokens tab; add a fresh
one and it resumes automatically.

---

## Reference backend (optional)

The Python pipeline that the app mirrors still runs standalone:

```bash
pip install -r requirements.txt        # curl-cffi is required for the Cloudflare bypass
python server/main.py                  # FastAPI web UI at http://127.0.0.1:8000
```

See [`docs/CONTEXT.md`](docs/CONTEXT.md) for the full gateway protocol and data shapes.

---

## Legal & responsible use

This project is for **personal, private use** — downloading content you are entitled to
access with your own account. Respect fictionzone.net's terms of service, keep delays
reasonable, and do not redistribute scraped content. You are responsible for how you use it.

## License

[MIT](LICENSE)
