package com.antigravity.noveldownloader.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.net.URI

/**
 * Parses a fictionzone.net novel landing page into [NovelMeta].
 * Ported from the reference `parser.py`.
 */
object HtmlParser {

    private val lenientJson = Json { ignoreUnknownKeys = true; isLenient = true }

    private val META_RE = Regex(
        """<meta\s+[^>]*?(?:name|property)=["']([^"']+)["']\s+[^>]*?content=["']([^"']*)["']""",
        RegexOption.IGNORE_CASE
    )
    private val TITLE_RE = Regex("""<title[^>]*>([^<]+)</title>""", RegexOption.IGNORE_CASE)
    private val JSONLD_RE = Regex(
        """<script[^>]+type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)
    )
    private val SRC_RE = Regex("""src=["']([^"']+)["']""", RegexOption.IGNORE_CASE)

    private fun parseMeta(html: String): Map<String, String> {
        val out = HashMap<String, String>()
        for (m in META_RE.findAll(html)) {
            out[m.groupValues[1].lowercase()] = m.groupValues[2]
        }
        TITLE_RE.find(html)?.let { out.putIfAbsent("html:title", it.groupValues[1].trim()) }
        return out
    }

    private fun parseJsonLd(html: String): List<JsonObject> {
        val blocks = ArrayList<JsonObject>()
        for (m in JSONLD_RE.findAll(html)) {
            val raw = m.groupValues[1].trim()
            val cleaned = raw.replace(Regex(""",\s*([}\]])"""), "$1")
            try {
                val el = lenientJson.parseToJsonElement(cleaned)
                when (el) {
                    is JsonObject -> blocks.add(el)
                    else -> el.let {
                        if (it is kotlinx.serialization.json.JsonArray) {
                            it.forEach { item -> if (item is JsonObject) blocks.add(item) }
                        }
                    }
                }
            } catch (_: Exception) { /* skip malformed */ }
        }
        return blocks
    }

    private fun findCoverUrl(html: String, meta: Map<String, String>): String? {
        for (key in listOf("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")) {
            meta[key]?.let { if (it.isNotBlank()) return it }
        }
        val coverDiv = Regex(
            """<div[^>]*class=["'][^"']*cover[^"']*["'][^>]*>(.*?)</div>""",
            setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)
        ).find(html)
        if (coverDiv != null) {
            SRC_RE.find(coverDiv.groupValues[1])?.let { return it.groupValues[1] }
        }
        return null
    }

    private fun findDescription(meta: Map<String, String>, blocks: List<JsonObject>): String {
        for (b in blocks) {
            (b["description"] as? JsonPrimitive)?.contentOrNull()?.let { if (it.isNotBlank()) return it.trim() }
        }
        for (key in listOf("og:description", "twitter:description", "description")) {
            meta[key]?.let { if (it.isNotBlank()) return it.trim() }
        }
        return ""
    }

    private fun findAuthor(meta: Map<String, String>, blocks: List<JsonObject>): String {
        for (b in blocks) {
            when (val author = b["author"]) {
                is JsonObject -> (author["name"] as? JsonPrimitive)?.contentOrNull()?.let { if (it.isNotBlank()) return it.trim() }
                is JsonPrimitive -> author.contentOrNull()?.let { if (it.isNotBlank()) return it.trim() }
                else -> {}
            }
        }
        return (meta["author"]?.trim()?.takeIf { it.isNotEmpty() })
            ?: (meta["book:author"]?.trim()?.takeIf { it.isNotEmpty() })
            ?: "Unknown"
    }

    private fun findGenres(html: String, meta: Map<String, String>): List<String> {
        val raw = meta["book:tag"]?.takeIf { it.isNotBlank() } ?: meta["keywords"].orEmpty()
        if (raw.isNotBlank()) {
            return raw.split(Regex("[,;|]")).map { it.trim() }.filter { it.isNotEmpty() }
        }
        return Regex(
            """<a[^>]+class=["'][^"']*genre[^"']*["'][^>]*>([^<]+)</a>""",
            setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)
        ).findAll(html).map { it.groupValues[1].trim() }.filter { it.isNotEmpty() }.toList()
    }

    fun findNovelIdFromHtml(html: String): String? {
        val patterns = listOf(
            """["']?novel_id["']?\s*[:=]\s*["']?(\d+)["']?""",
            """["']?novelId["']?\s*[:=]\s*["']?(\d+)["']?""",
            """data-novel-id=["']?(\d+)["']?""",
            """novel-id=["']?(\d+)["']?""",
            """/novel/[^/]+/(\d+)""",
            """/novel/[^/]+-(\d+)""",
            """chapter-lists.*novel_id=(\d+)""",
            """novel-detail.*novel_id=(\d+)""",
        )
        for (p in patterns) {
            Regex(p).find(html)?.let { return it.groupValues[1] }
        }
        return null
    }

    /** Returns parsed metadata, or null if the novel id cannot be determined. */
    fun parse(html: String, pageUrl: String, fallbackNovelId: String? = null): NovelMeta? {
        val meta = parseMeta(html)
        val jsonld = parseJsonLd(html)

        var title = (meta["og:title"] ?: meta["twitter:title"] ?: meta["html:title"] ?: "").trim()
        title = title.replace(Regex("""\s*[-|–—]\s*FictionZone\s*$""", RegexOption.IGNORE_CASE), "")
        if (title.isBlank()) title = if (fallbackNovelId != null) "Novel $fallbackNovelId" else "Unknown Novel"

        var coverUrl = findCoverUrl(html, meta)
        if (coverUrl != null) {
            coverUrl = try {
                URI(pageUrl).resolve(coverUrl).toString()
            } catch (_: Exception) {
                coverUrl
            }
        }

        val novelId = findNovelIdFromHtml(html) ?: fallbackNovelId ?: return null

        return NovelMeta(
            novelId = novelId,
            title = title,
            author = findAuthor(meta, jsonld),
            description = findDescription(meta, jsonld),
            coverUrl = coverUrl,
            status = meta["book:status"]?.trim().orEmpty(),
            genres = findGenres(html, meta),
            sourceUrl = pageUrl,
        )
    }

    private fun JsonPrimitive.contentOrNull(): String? =
        if (this is JsonNull) null else this.content
}
