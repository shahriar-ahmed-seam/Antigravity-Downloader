package com.antigravity.noveldownloader.core

import android.content.Context
import kotlinx.serialization.json.Json
import java.io.File
import java.text.Normalizer

/**
 * On-disk store for novels: metadata, chapter index, chapter text files and EPUBs.
 * Ported from the reference `cache.py`. Files live under the app's external files
 * directory: `<externalFilesDir>/books/<novelId>/`.
 */
class NovelCache(context: Context) {

    private val json = Json { prettyPrint = true; ignoreUnknownKeys = true; encodeDefaults = true }

    val booksDir: File = File(
        context.getExternalFilesDir(null) ?: context.filesDir,
        "books"
    ).apply { mkdirs() }

    fun novelDir(novelId: String): File = File(booksDir, novelId).apply { mkdirs() }

    fun chaptersDir(novelId: String): File = File(novelDir(novelId), "chapters").apply { mkdirs() }

    fun saveBookInfo(novelId: String, meta: NovelMeta) {
        File(novelDir(novelId), "info.json").writeText(json.encodeToString(NovelMeta.serializer(), meta))
    }

    fun getBookInfo(novelId: String): NovelMeta? {
        val f = File(novelDir(novelId), "info.json")
        if (!f.exists()) return null
        return try {
            json.decodeFromString(NovelMeta.serializer(), f.readText())
        } catch (_: Exception) {
            null
        }
    }

    fun saveChapterIndex(novelId: String, chapters: List<ChapterRef>) {
        val payload = ChapterIndex(novelId, chapters.size, chapters)
        File(novelDir(novelId), "chapters.json").writeText(json.encodeToString(ChapterIndex.serializer(), payload))
    }

    fun getChapterIndex(novelId: String): List<ChapterRef>? {
        val f = File(novelDir(novelId), "chapters.json")
        if (!f.exists()) return null
        return try {
            json.decodeFromString(ChapterIndex.serializer(), f.readText()).chapters
        } catch (_: Exception) {
            null
        }
    }

    fun isChapterCached(novelId: String, idx: Int): Boolean {
        val prefix = "%04d - ".format(idx)
        return chaptersDir(novelId).listFiles()?.any {
            it.name.startsWith(prefix) && it.name.endsWith(".txt")
        } ?: false
    }

    /** Verbatim text retention with normalised spacing and line endings. */
    fun normalizeText(raw: String?): String {
        if (raw.isNullOrEmpty()) return ""
        var text = raw.replace("\r\n", "\n").replace("\r", "\n")
        text = text.split("\n").joinToString("\n") { it.trimEnd() }
        text = text.replace(Regex("\n{3,}"), "\n\n")
        return text.trim('\n') + "\n"
    }

    fun saveChapterFile(
        novelId: String,
        idx: Int,
        title: String,
        chapterId: String,
        rawContent: String,
        force: Boolean = false,
    ): File {
        val safeTitle = safeFilename(title, "Untitled")
        val file = File(chaptersDir(novelId), "%04d - %s.txt".format(idx, safeTitle))
        if (file.exists() && !force) return file
        val normalized = normalizeText(rawContent)
        file.writeText("$title\n\n$normalized")
        return file
    }

    fun findCoverFile(novelId: String): File? {
        val dir = novelDir(novelId)
        for (ext in listOf("jpg", "jpeg", "png", "webp", "gif")) {
            val f = File(dir, "cover.$ext")
            if (f.exists()) return f
        }
        return null
    }

    fun listBooks(): List<LibraryBook> {
        val dir = booksDir
        val out = ArrayList<LibraryBook>()
        dir.listFiles()?.forEach { p ->
            if (p.isDirectory && !p.name.startsWith(".")) {
                val novelId = p.name
                val info = getBookInfo(novelId) ?: NovelMeta(
                    novelId = novelId,
                    title = "Novel $novelId",
                    author = "Unknown",
                    description = "No metadata downloaded.",
                )
                val index = getChapterIndex(novelId)
                val downloaded = File(p, "chapters").listFiles()?.count { it.name.endsWith(".txt") } ?: 0
                val epub = p.listFiles()?.firstOrNull { it.name.endsWith(".epub") }?.name
                val cover = findCoverFile(novelId)?.name
                out.add(
                    LibraryBook(
                        novelId = novelId,
                        meta = info,
                        totalChapters = index?.size ?: 0,
                        downloadedChapters = downloaded,
                        epubFilename = epub,
                        coverFile = cover,
                        lastModified = p.lastModified(),
                    )
                )
            }
        }
        return out.sortedByDescending { it.lastModified }
    }

    fun deleteBook(novelId: String): Boolean {
        val dir = File(booksDir, novelId)
        return if (dir.exists()) dir.deleteRecursively() else false
    }

    companion object {
        private val FILENAME_SAFE_RE = Regex("""[^\w\-. ]+""")

        fun safeFilename(name: String?, fallback: String = "untitled"): String {
            if (name.isNullOrBlank()) return fallback
            var cleaned = Normalizer.normalize(name, Normalizer.Form.NFKC).trim()
            cleaned = cleaned.filter { it.code >= 32 && it != '\n' && it != '\r' && it != '\t' }
            cleaned = FILENAME_SAFE_RE.replace(cleaned, "_")
            cleaned = Regex("""\s+""").replace(cleaned, " ").trim(' ', '.', '_')
            return if (cleaned.isBlank() || cleaned.length > 200) fallback else cleaned
        }
    }
}
