package com.antigravity.noveldownloader.core

import android.content.Context
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.random.Random

private class AbortSignal : Exception()

/**
 * Singleton that owns the live download: state, console logs, flow control
 * (pause/resume/abort), multi-token rotation and the scrape loop itself.
 *
 * Mirrors the reference `scraper.py` behaviour: randomised fetch order, a
 * user-defined random delay window between requests, resume-safe caching and
 * automatic EPUB compilation on completion.
 */
object DownloadController {

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private val _state = MutableStateFlow(DownloadState())
    val state: StateFlow<DownloadState> = _state.asStateFlow()

    private val _logs = MutableStateFlow<List<LogLine>>(emptyList())
    val logs: StateFlow<List<LogLine>> = _logs.asStateFlow()

    private val paused = MutableStateFlow(false)

    @Volatile private var aborted = false
    @Volatile private var running = false

    @Volatile private var liveTokens: List<String> = emptyList()
    private val deadTokens = HashSet<String>()
    private var tokenWaiter: CompletableDeferred<Unit>? = null
    private var rrIndex = 0

    val isRunning: Boolean get() = running

    // --- Control surface (called from UI / service) ---

    fun pause() {
        if (running && _state.value.status == JobStatus.RUNNING) {
            paused.value = true
        }
    }

    fun resume() {
        paused.value = false
    }

    fun abort() {
        aborted = true
        paused.value = false
        tokenWaiter?.takeIf { !it.isCompleted }?.complete(Unit)
    }

    /** Called when the user adds/edits tokens while a run is waiting on auth. */
    fun notifyTokensUpdated(tokens: List<String>) {
        liveTokens = tokens.filter { it !in deadTokens }
        if (liveTokens.isNotEmpty()) {
            tokenWaiter?.takeIf { !it.isCompleted }?.complete(Unit)
        }
    }

    fun clearLogs() { _logs.value = emptyList() }

    fun resetIfFinished() {
        if (!running) _state.value = DownloadState()
    }

    private fun log(message: String, level: String = "info") {
        val updated = (_logs.value + LogLine(level, message)).takeLast(600)
        _logs.value = updated
    }

    private fun setStatus(status: JobStatus, error: String? = null, epub: String? = null) {
        _state.value = _state.value.copy(status = status, error = error ?: _state.value.error, epubFile = epub ?: _state.value.epubFile)
    }

    // --- Main entry point ---

    suspend fun run(context: Context, config: DownloadConfig, tokens: List<String>, title: String) {
        if (running) return
        running = true
        aborted = false
        paused.value = false
        deadTokens.clear()
        rrIndex = 0
        liveTokens = tokens.toList()

        _state.value = DownloadState(status = JobStatus.RUNNING, novelId = config.novelId, title = title)

        val cache = NovelCache(context)
        try {
            log("Starting download for novel ${config.novelId}")
            log("Warming up the Chromium network engine…")
            GatewayEngine.init(context)
            if (!GatewayEngine.awaitReady()) {
                fail("Could not warm up the network engine (Cloudflare warm-up timed out).")
                return
            }
            log("Engine ready. TLS handled by the on-device Chromium stack.", "success")

            if (liveTokens.isEmpty()) {
                log("No tokens available. Add at least one bearer token to continue.", "warn")
                awaitTokens()
                if (aborted) { finishAborted(); return }
            }

            val chapters = ensureIndex(config, cache)
            if (aborted) { finishAborted(); return }
            log("Canonical index holds ${chapters.size} chapters.")

            // Range filter.
            val selected = chapters.filterIndexed { i, e ->
                val cur = e.idx ?: (i + 1)
                (config.startChapter == null || cur >= config.startChapter) &&
                    (config.endChapter == null || cur <= config.endChapter)
            }
            if (selected.isEmpty()) {
                fail("No chapters match the selected range.")
                return
            }
            log("Range selects ${selected.size} chapters.")

            // Pending = not yet cached (unless force).
            var skipped = 0
            val pending = ArrayList<ChapterRef>()
            for (e in selected) {
                val idx = e.idx ?: 0
                if (config.force || !cache.isChapterCached(config.novelId, idx)) pending.add(e) else skipped++
            }
            _state.value = _state.value.copy(total = pending.size, completed = 0, skipped = skipped)
            log("$skipped already cached; ${pending.size} to fetch.")

            if (config.shuffle) {
                pending.shuffle()
                log("Fetch order shuffled.")
            }

            var consecutiveFailures = 0
            val maxFailures = 5
            var i = 0
            while (i < pending.size) {
                checkControl()
                if (aborted) { finishAborted(); return }

                val entry = pending[i]
                val cIdx = if (config.renumber) (i + 1) else (entry.idx ?: (i + 1))
                val cId = entry.id
                val cTitle = entry.title.ifBlank { "Chapter $cIdx" }

                val token = nextToken()
                if (token == null) {
                    awaitTokens()
                    if (aborted) { finishAborted(); return }
                    continue
                }

                log("Fetching ${i + 1}/${pending.size}: idx=$cIdx [$cId] — $cTitle")
                _state.value = _state.value.copy(currentChapter = cTitle)

                val result = GatewayEngine.postGateway(
                    "/platform/chapter-content",
                    mapOf("novel_id" to config.novelId, "chapter_id" to cId, "highlight" to config.highlight),
                    token,
                )

                when (val outcome = interpret(result)) {
                    is Outcome.Auth -> {
                        log("Token ${TokenStore.info(token).preview} rejected (${outcome.reason}). Rotating.", "warn")
                        deadTokens.add(token)
                        liveTokens = liveTokens.filter { it !in deadTokens }
                        // Do not advance i — retry same chapter with another token.
                        continue
                    }
                    is Outcome.Net -> {
                        consecutiveFailures++
                        log("Network error: ${outcome.reason} ($consecutiveFailures/$maxFailures)", "warn")
                        if (consecutiveFailures >= maxFailures) {
                            fail("Aborted: too many consecutive network failures.")
                            return
                        }
                        delay(3000)
                        continue
                    }
                    is Outcome.Ok -> {
                        cache.saveChapterFile(config.novelId, cIdx, cTitle, cId, outcome.content, force = true)
                        consecutiveFailures = 0
                        _state.value = _state.value.copy(completed = _state.value.completed + 1)
                        log("Saved idx=$cIdx — $cTitle", "success")

                        if (i < pending.size - 1) {
                            val lo = minOf(config.delayMin, config.delayMax)
                            val hi = maxOf(config.delayMin, config.delayMax)
                            val secs = if (hi <= lo) lo else lo + Random.nextDouble() * (hi - lo)
                            log("Sleeping %.2fs…".format(secs))
                            delay((secs * 1000).toLong())
                        }
                        i++
                    }
                }
            }

            log("All chapters retrieved. Compiling EPUB…")
            val epub = EpubBuilder(cache).compile(config.novelId, config.startChapter, config.endChapter)
            log("EPUB compiled: ${epub.name}", "success")

            val saved = try {
                log("Exporting to ${Exporter.PUBLIC_DISPLAY}…")
                Exporter.saveToDownloads(context, epub).also { log("Saved to $it", "success") }
            } catch (e: Exception) {
                log("Public export failed (${e.message}); the EPUB is still in the in-app library.", "warn")
                null
            }

            _state.value = _state.value.copy(
                status = JobStatus.COMPLETED,
                epubFile = epub.name,
                savedPath = saved,
                currentChapter = "",
            )
        } catch (e: AbortSignal) {
            finishAborted()
        } catch (e: Exception) {
            fail(e.message ?: "Unexpected error")
        } finally {
            running = false
        }
    }

    // --- Helpers ---

    private sealed class Outcome {
        data class Ok(val content: String) : Outcome()
        data class Auth(val reason: String) : Outcome()
        data class Net(val reason: String) : Outcome()
    }

    private fun interpret(result: GatewayResult): Outcome {
        if (result.status == 401) return Outcome.Auth("HTTP 401")
        if (!result.ok && result.status == 0) return Outcome.Net(result.error ?: "transport error")
        return try {
            val obj = json.parseToJsonElement(result.body).jsonObject
            val success = obj["success"]?.jsonPrimitive?.booleanOrNull ?: false
            val message = obj["message"]?.jsonPrimitive?.contentOrNull().orEmpty()
            if (!success) {
                val lower = message.lowercase()
                if (lower.contains("login to continue") || lower.contains("unauthorized") || lower.contains("token")) {
                    Outcome.Auth(message.ifBlank { "rejected" })
                } else {
                    Outcome.Net(message.ifBlank { "gateway error" })
                }
            } else {
                val content = obj["data"]?.jsonObject?.get("content")?.jsonPrimitive?.contentOrNull().orEmpty()
                Outcome.Ok(content)
            }
        } catch (e: Exception) {
            Outcome.Net("invalid response (not JSON)")
        }
    }

    private fun nextToken(): String? {
        val live = liveTokens.filter { it !in deadTokens }
        if (live.isEmpty()) return null
        return when {
            live.size == 1 -> live[0]
            else -> {
                // ROUND_ROBIN default; randomness in order is already provided by shuffle.
                val t = live[rrIndex % live.size]
                rrIndex = (rrIndex + 1) % live.size
                t
            }
        }
    }

    private suspend fun awaitTokens() {
        setStatus(JobStatus.TOKEN_EXPIRED)
        log("Waiting for a working token. Add or refresh one in the Tokens panel.", "warn")
        val waiter = CompletableDeferred<Unit>()
        tokenWaiter = waiter
        waiter.await()
        tokenWaiter = null
        if (!aborted) {
            setStatus(JobStatus.RUNNING)
            log("Token(s) updated. Resuming.", "success")
        }
    }

    private suspend fun checkControl() {
        if (paused.value && _state.value.status == JobStatus.RUNNING) {
            setStatus(JobStatus.PAUSED)
            log("Paused.")
            paused.first { !it }
            if (!aborted) {
                setStatus(JobStatus.RUNNING)
                log("Resumed.")
            }
        }
        if (aborted) throw AbortSignal()
    }

    private suspend fun ensureIndex(config: DownloadConfig, cache: NovelCache): List<ChapterRef> {
        val existing = cache.getChapterIndex(config.novelId)
        if (existing != null && existing.isNotEmpty() && !config.refreshIndex) return existing

        log("Fetching chapter index from gateway…")
        val collected = ArrayList<ChapterRef>()
        val seen = HashSet<String>()
        var page = 1
        val pageSize = 200
        val maxPages = 100

        while (page <= maxPages) {
            if (aborted) return emptyList()
            val token = nextToken() ?: run { awaitTokens(); nextToken() }
            if (token == null) { if (aborted) return emptyList() else continue }

            val resp = GatewayEngine.postGateway(
                "/platform/chapter-lists",
                mapOf("novel_id" to config.novelId, "page" to page, "page_size" to pageSize),
                token,
            )
            when (val outcome = interpretList(resp)) {
                is ListOutcome.Auth -> {
                    log("Token rejected fetching index. Rotating.", "warn")
                    deadTokens.add(token)
                    liveTokens = liveTokens.filter { it !in deadTokens }
                    if (liveTokens.isEmpty()) { awaitTokens(); if (aborted) return emptyList() }
                    continue
                }
                is ListOutcome.Net -> throw IllegalStateException("Failed to fetch chapter index: ${outcome.reason}")
                is ListOutcome.Ok -> {
                    val raw = outcome.entries
                    if (raw.isEmpty()) break
                    var newCount = 0
                    for (e in raw) {
                        if (e.id in seen) continue
                        seen.add(e.id)
                        collected.add(e)
                        newCount++
                    }
                    log("Page $page: +$newCount (index size ${collected.size})")
                    val total = outcome.total
                    if (total != null && collected.size >= total) break
                    if (newCount == 0 || newCount < raw.size) break
                    page++
                }
            }
        }

        if (collected.isEmpty()) throw IllegalStateException("Gateway returned an empty chapter index.")

        // Sort by idx (nulls last), assign fallback sequence if all missing.
        collected.sortWith(compareBy({ it.idx == null }, { it.idx ?: 0 }, { it.id }))
        val finalList = if (collected.all { it.idx == null }) {
            collected.mapIndexed { i, e -> e.copy(idx = i + 1) }
        } else collected

        cache.saveChapterIndex(config.novelId, finalList)
        return finalList
    }

    private sealed class ListOutcome {
        data class Ok(val entries: List<ChapterRef>, val total: Int?) : ListOutcome()
        data class Auth(val reason: String) : ListOutcome()
        data class Net(val reason: String) : ListOutcome()
    }

    private fun interpretList(result: GatewayResult): ListOutcome {
        if (result.status == 401) return ListOutcome.Auth("HTTP 401")
        if (!result.ok && result.status == 0) return ListOutcome.Net(result.error ?: "transport error")
        return try {
            val obj = json.parseToJsonElement(result.body).jsonObject
            val success = obj["success"]?.jsonPrimitive?.booleanOrNull ?: false
            val message = obj["message"]?.jsonPrimitive?.contentOrNull().orEmpty()
            if (!success) {
                val lower = message.lowercase()
                return if (lower.contains("login") || lower.contains("unauthorized") || lower.contains("token"))
                    ListOutcome.Auth(message) else ListOutcome.Net(message.ifBlank { "gateway error" })
            }
            val data = obj["data"]
            val arr = when {
                data is kotlinx.serialization.json.JsonObject ->
                    data["chapters"] ?: data["list"] ?: data["items"]
                else -> data
            }
            val list = (arr as? kotlinx.serialization.json.JsonArray)?.mapNotNull { el ->
                val o = el.jsonObject
                val cid = (o["id"] ?: o["chapter_id"] ?: o["_id"])?.jsonPrimitive?.contentOrNull() ?: return@mapNotNull null
                val t = (o["title"] ?: o["name"])?.jsonPrimitive?.contentOrNull().orEmpty().trim()
                val idx = (o["idx"] ?: o["order"] ?: o["index"] ?: o["chapter_no"] ?: o["chapter_number"])
                    ?.jsonPrimitive?.contentOrNull()?.toDoubleOrNull()?.toInt()
                ChapterRef(cid, t, idx)
            } ?: emptyList()
            val total = (data as? kotlinx.serialization.json.JsonObject)
                ?.let { it["total"] ?: it["total_count"] }?.jsonPrimitive?.contentOrNull()?.toIntOrNull()
            ListOutcome.Ok(list, total)
        } catch (e: Exception) {
            ListOutcome.Net("invalid response (not JSON)")
        }
    }

    private fun fail(reason: String) {
        log(reason, "error")
        _state.value = _state.value.copy(status = JobStatus.FAILED, error = reason, currentChapter = "")
    }

    private fun finishAborted() {
        log("Aborted by user.", "warn")
        _state.value = _state.value.copy(status = JobStatus.ABORTED, currentChapter = "")
    }

    private fun kotlinx.serialization.json.JsonPrimitive.contentOrNull(): String? =
        if (this is kotlinx.serialization.json.JsonNull) null else this.content
}
