package com.antigravity.noveldownloader.core

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Result of analysing a novel landing page. */
data class AnalyzeResult(
    val meta: NovelMeta,
    val chapters: List<ChapterRef>,
)

/** Fetches and parses a novel's metadata + chapter index, mirroring `/api/novel/info`. */
class NovelAnalyzer(private val context: Context) {

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    suspend fun analyze(url: String, fallbackNovelId: String?, tokens: List<String>): Result<AnalyzeResult> {
        if (!url.contains("fictionzone.net/novel/")) {
            return Result.failure(IllegalArgumentException("URL must contain fictionzone.net/novel/"))
        }
        GatewayEngine.init(context)
        if (!GatewayEngine.awaitReady()) {
            return Result.failure(IllegalStateException("Network engine warm-up timed out."))
        }

        val htmlRes = GatewayEngine.getHtml(url)
        if (!htmlRes.ok || htmlRes.body.isBlank()) {
            return Result.failure(IllegalStateException("Could not load the novel page (${htmlRes.error ?: htmlRes.status})."))
        }

        val meta = HtmlParser.parse(htmlRes.body, url, fallbackNovelId)
            ?: return Result.failure(IllegalStateException("Could not determine novel id. Enter it manually."))

        val cache = NovelCache(context)
        cache.saveBookInfo(meta.novelId, meta)

        // Cover (best-effort).
        meta.coverUrl?.let { coverUrl ->
            GatewayEngine.getBytes(coverUrl)?.let { bytes ->
                val ext = Regex("""\.([a-zA-Z0-9]{2,5})(?:\?|$)""").find(coverUrl)?.groupValues?.get(1)?.lowercase()
                    ?.takeIf { it in listOf("jpg", "jpeg", "png", "webp", "gif") } ?: "jpg"
                val coverFile = java.io.File(cache.novelDir(meta.novelId), "cover.$ext")
                coverFile.writeBytes(bytes)
                meta.coverPath = coverFile.name
                cache.saveBookInfo(meta.novelId, meta)
            }
        }

        // Chapter index (cached or fetched).
        var chapters = cache.getChapterIndex(meta.novelId)
        if (chapters.isNullOrEmpty()) {
            chapters = runCatching { fetchIndex(meta.novelId, tokens) }.getOrDefault(emptyList())
            if (chapters.isNotEmpty()) cache.saveChapterIndex(meta.novelId, chapters)
        }

        return Result.success(AnalyzeResult(meta, chapters))
    }

    private suspend fun fetchIndex(novelId: String, tokens: List<String>): List<ChapterRef> {
        if (tokens.isEmpty()) return emptyList()
        val collected = ArrayList<ChapterRef>()
        val seen = HashSet<String>()
        var page = 1
        val pageSize = 200
        val maxPages = 100
        var tokenIdx = 0

        while (page <= maxPages) {
            val token = tokens[tokenIdx % tokens.size]
            val resp = GatewayEngine.postGateway(
                "/platform/chapter-lists",
                mapOf("novel_id" to novelId, "page" to page, "page_size" to pageSize),
                token,
            )
            val obj = try {
                json.parseToJsonElement(resp.body).jsonObject
            } catch (e: Exception) {
                break
            }
            val success = obj["success"]?.jsonPrimitive?.booleanOrNull ?: false
            if (!success) {
                // Try another token once, else give up.
                tokenIdx++
                if (tokenIdx >= tokens.size) break else continue
            }
            val data = obj["data"]
            val arr = when (data) {
                is JsonObject -> data["chapters"] ?: data["list"] ?: data["items"]
                else -> data
            } as? JsonArray ?: break
            if (arr.isEmpty()) break

            var newCount = 0
            for (el in arr) {
                val o = el.jsonObject
                val cid = (o["id"] ?: o["chapter_id"] ?: o["_id"])?.jsonPrimitive?.contentOrNull() ?: continue
                if (cid in seen) continue
                seen.add(cid)
                val t = (o["title"] ?: o["name"])?.jsonPrimitive?.contentOrNull().orEmpty().trim()
                val idx = (o["idx"] ?: o["order"] ?: o["index"] ?: o["chapter_no"] ?: o["chapter_number"])
                    ?.jsonPrimitive?.contentOrNull()?.toDoubleOrNull()?.toInt()
                collected.add(ChapterRef(cid, t, idx))
                newCount++
            }
            val total = (data as? JsonObject)?.let { it["total"] ?: it["total_count"] }
                ?.jsonPrimitive?.contentOrNull()?.toIntOrNull()
            if (total != null && collected.size >= total) break
            if (newCount == 0 || newCount < arr.size) break
            page++
        }

        collected.sortWith(compareBy({ it.idx == null }, { it.idx ?: 0 }, { it.id }))
        return if (collected.all { it.idx == null }) {
            collected.mapIndexed { i, e -> e.copy(idx = i + 1) }
        } else collected
    }

    private fun JsonPrimitive.contentOrNull(): String? = if (this is JsonNull) null else this.content
}
