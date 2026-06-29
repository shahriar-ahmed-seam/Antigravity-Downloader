package com.antigravity.noveldownloader.core

import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.zip.CRC32
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * Builds a valid EPUB3 from cached chapter text files using a pure zip writer.
 * Ported from the working `_build_with_zipfile` path in the reference
 * `epub_builder.py` (the EbookLib path was unreliable upstream).
 */
class EpubBuilder(private val cache: NovelCache) {

    private data class ParsedChapter(val title: String, val idx: Int?, val chapterId: String, val body: String)
    private data class CompiledChapter(val id: String, val idx: Int, val title: String, val body: String)

    fun compile(novelId: String, rangeStart: Int? = null, rangeEnd: Int? = null): File {
        val novelDir = cache.novelDir(novelId)
        val info = cache.getBookInfo(novelId) ?: NovelMeta(novelId = novelId, title = "Novel $novelId")
        val canonical = cache.getChapterIndex(novelId)
            ?: throw IllegalStateException("Chapter index (chapters.json) not found for novel $novelId")

        // 1. Scan and parse cached chapter files.
        val byId = HashMap<String, ParsedChapter>()
        val byIdx = HashMap<Int, ParsedChapter>()
        cache.chaptersDir(novelId).listFiles()?.filter { it.name.endsWith(".txt") }?.forEach { f ->
            try {
                val parsed = parseChapterFile(f)
                byId[parsed.chapterId] = parsed
                parsed.idx?.let { byIdx[it] = parsed }
            } catch (_: Exception) { /* skip unreadable file */ }
        }

        // 2. Match downloaded chapters against the canonical list, filter + dedup.
        val include = ArrayList<CompiledChapter>()
        val seenIds = HashSet<String>()
        val seenIdx = HashSet<Int>()
        canonical.forEachIndexed { i, entry ->
            val cid = entry.id
            val cIdx = entry.idx
            val currentIdx = cIdx ?: (i + 1)
            if (rangeStart != null && currentIdx < rangeStart) return@forEachIndexed
            if (rangeEnd != null && currentIdx > rangeEnd) return@forEachIndexed
            if (cid in seenIds || currentIdx in seenIdx) return@forEachIndexed

            val data = byId[cid] ?: (cIdx?.let { byIdx[it] })
            if (data != null) {
                seenIds.add(cid)
                seenIdx.add(currentIdx)
                include.add(
                    CompiledChapter(
                        id = cid,
                        idx = currentIdx,
                        title = entry.title.ifBlank { "Chapter $currentIdx" },
                        body = data.body,
                    )
                )
            }
        }

        if (include.isEmpty()) throw IllegalStateException("No downloaded chapters match the requested range.")

        val safeTitle = NovelCache.safeFilename(info.title, "Novel $novelId")
        val outPath = File(novelDir, "$safeTitle.epub")
        buildZip(novelId, info, include, outPath)
        return outPath
    }

    private fun parseChapterFile(file: File): ParsedChapter {
        val text = file.readText()
        val lines = text.split("\n")

        // Banner format: starts with a bar of '=' signs.
        if (lines.size >= 8 && lines[0].startsWith("===") && lines[0].replace("=", "").isBlank()) {
            val title = lines[1].trim()
            val idx = lines[2].replace("Chapter", "").trim().toIntOrNull()
            val body = lines.subList(8, lines.size).joinToString("\n")
            return ParsedChapter(title, idx, file.nameWithoutExtension, body)
        }

        // Clean format: "0001 - Title.txt", first content line is the title.
        val name = file.nameWithoutExtension
        var idxStr = "0"
        var title = name
        if (name.contains(" - ")) {
            val parts = name.split(" - ", limit = 2)
            idxStr = parts[0]
            title = lines.firstOrNull()?.trim()?.takeIf { it.isNotBlank() } ?: parts[1]
        } else if (lines.isNotEmpty()) {
            title = lines[0].trim()
        }
        var bodyStart = 1
        while (bodyStart < lines.size && lines[bodyStart].isBlank()) bodyStart++
        val body = if (bodyStart < lines.size) lines.subList(bodyStart, lines.size).joinToString("\n") else ""
        return ParsedChapter(title, idxStr.trim().toIntOrNull(), name, body)
    }

    private fun buildZip(novelId: String, info: NovelMeta, chapters: List<CompiledChapter>, outPath: File) {
        val title = info.title.ifBlank { "Novel $novelId" }
        val author = info.author.ifBlank { "Unknown" }
        val description = info.description

        val coverFile = cache.findCoverFile(novelId)
        var coverName: String? = null
        var coverMime: String? = null
        var coverData: ByteArray? = null
        if (coverFile != null) {
            val suffix = coverFile.extension.lowercase()
            coverMime = when (suffix) {
                "jpg", "jpeg" -> "image/jpeg"
                "png" -> "image/png"
                "webp" -> "image/webp"
                "gif" -> "image/gif"
                else -> "image/jpeg"
            }
            coverName = "cover.$suffix"
            coverData = coverFile.readBytes()
        }

        val manifest = StringBuilder()
        val spine = StringBuilder()
        val tocItems = StringBuilder()

        ZipOutputStream(outPath.outputStream().buffered()).use { zos ->
            // 1. mimetype — must be the first entry and stored uncompressed.
            val mimeBytes = "application/epub+zip".toByteArray(Charsets.US_ASCII)
            val mimeEntry = ZipEntry("mimetype").apply {
                method = ZipEntry.STORED
                size = mimeBytes.size.toLong()
                compressedSize = mimeBytes.size.toLong()
                crc = CRC32().apply { update(mimeBytes) }.value
            }
            zos.putNextEntry(mimeEntry)
            zos.write(mimeBytes)
            zos.closeEntry()

            zos.setMethod(ZipOutputStream.DEFLATED)

            fun writeEntry(name: String, data: ByteArray) {
                zos.putNextEntry(ZipEntry(name))
                zos.write(data)
                zos.closeEntry()
            }

            // 2. container.xml
            writeEntry(
                "META-INF/container.xml",
                ("""<?xml version="1.0" encoding="UTF-8"?>
                    |<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">""" +
                    """<rootfiles><rootfile full-path="OEBPS/content.opf" """ +
                    """media-type="application/oebps-package+xml"/></rootfiles></container>""").trimMargin()
                    .toByteArray()
            )

            // 3. Cover
            if (coverData != null && coverName != null) {
                writeEntry("OEBPS/$coverName", coverData)
                manifest.append("""<item id="cover-img" href="$coverName" media-type="$coverMime" properties="cover-image"/>""")
                val coverXhtml = """<?xml version="1.0" encoding="UTF-8"?>
                    |<!DOCTYPE html>
                    |<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head><meta charset="utf-8"/><title>Cover</title>
                    |<style>body { text-align:center; margin:0; padding:0; } img { max-width:100%; height:auto; }</style></head>
                    |<body><img src="$coverName" alt="Cover"/></body></html>""".trimMargin()
                writeEntry("OEBPS/cover.xhtml", coverXhtml.toByteArray())
                manifest.append("""<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>""")
                spine.append("""<itemref idref="cover"/>""")
            }

            // 4. Info page
            val genresStr = info.genres.joinToString(", ")
            val statusStr = info.status.ifBlank { "Unknown" }
            val infoXhtml = """<?xml version="1.0" encoding="UTF-8"?>
                |<!DOCTYPE html>
                |<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head><meta charset="utf-8"/><title>Book Information</title></head>
                |<body><h1>${esc(title)}</h1>
                |<p><strong>Author:</strong> ${esc(author)}</p>
                |<p><strong>Status:</strong> ${esc(statusStr)}</p>
                |<p><strong>Genres:</strong> ${esc(genresStr)}</p>
                |<h3>Synopsis</h3><div>${paragraphsToHtml(description)}</div></body></html>""".trimMargin()
            writeEntry("OEBPS/info.xhtml", infoXhtml.toByteArray())
            manifest.append("""<item id="info" href="info.xhtml" media-type="application/xhtml+xml"/>""")
            spine.append("""<itemref idref="info"/>""")

            // 5. Chapters
            for (chap in chapters) {
                val fileId = "chap%04d".format(chap.idx)
                val fileName = "$fileId.xhtml"
                val bodyHtml = paragraphsToHtml(chap.body)
                val xhtml = """<?xml version="1.0" encoding="UTF-8"?>
                    |<!DOCTYPE html>
                    |<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head><meta charset="utf-8"/>
                    |<title>${esc(chap.title)}</title></head>
                    |<body><h1>${esc(chap.title)}</h1><p><em>Chapter ${chap.idx}</em></p>$bodyHtml</body></html>""".trimMargin()
                writeEntry("OEBPS/$fileName", xhtml.toByteArray())
                manifest.append("""<item id="$fileId" href="$fileName" media-type="application/xhtml+xml"/>""")
                spine.append("""<itemref idref="$fileId"/>""")
                tocItems.append("""<li><a href="$fileName">${esc(chap.title)}</a></li>""")
            }

            // 6. nav.xhtml
            val nav = """<?xml version="1.0" encoding="UTF-8"?>
                |<!DOCTYPE html>
                |<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">
                |<head><meta charset="utf-8"/><title>Table of Contents</title></head>
                |<body><nav epub:type="toc" id="toc"><h1>Table of Contents</h1><ol>$tocItems</ol></nav></body></html>""".trimMargin()
            writeEntry("OEBPS/nav.xhtml", nav.toByteArray())
            manifest.append("""<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>""")
            spine.append("""<itemref idref="nav"/>""")

            // 7. content.opf
            val nowStr = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
                timeZone = TimeZone.getTimeZone("UTC")
            }.format(Date())
            val opf = """<?xml version="1.0" encoding="UTF-8"?>
                |<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" lang="en">
                |<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                |<dc:identifier id="bookid">fictionzone-${esc(novelId)}</dc:identifier>
                |<dc:title>${esc(title)}</dc:title><dc:creator>${esc(author)}</dc:creator>
                |<dc:language>en</dc:language><dc:description>${esc(description)}</dc:description>
                |<meta property="dcterms:modified">$nowStr</meta></metadata>
                |<manifest>$manifest</manifest><spine>$spine</spine></package>""".trimMargin()
            writeEntry("OEBPS/content.opf", opf.toByteArray())
        }
    }

    companion object {
        fun esc(text: String): String = text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\"", "&quot;")
            .replace("'", "&apos;")

        fun paragraphsToHtml(body: String): String {
            return body.split("\n").joinToString("\n") { line ->
                val stripped = line.trim()
                if (stripped.isNotEmpty()) "<p>${esc(stripped)}</p>" else "<p>&#160;</p>"
            }
        }
    }
}
