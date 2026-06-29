package com.antigravity.noveldownloader.core

import kotlinx.serialization.Serializable

/** Normalised book metadata, mirrors the Python `info.json` shape. */
@Serializable
data class NovelMeta(
    val novelId: String,
    val title: String,
    val author: String = "Unknown",
    val description: String = "",
    val coverUrl: String? = null,
    val status: String = "",
    val genres: List<String> = emptyList(),
    val sourceUrl: String = "",
    var coverPath: String? = null,
)

/** A single chapter reference from the canonical index (`chapters.json`). */
@Serializable
data class ChapterRef(
    val id: String,
    val title: String,
    val idx: Int? = null,
)

/** Persisted on disk per novel (`chapters.json`). */
@Serializable
data class ChapterIndex(
    val novelId: String,
    val count: Int,
    val chapters: List<ChapterRef>,
)

/** Result of a single gateway / HTTP call performed by the WebView engine. */
data class GatewayResult(
    val ok: Boolean,
    val status: Int,
    val body: String,
    val error: String? = null,
)

/** Lifecycle state of a download job. */
enum class JobStatus { IDLE, RUNNING, PAUSED, TOKEN_EXPIRED, COMPLETED, FAILED, ABORTED }

/** A single console log line. */
data class LogLine(
    val level: String,
    val message: String,
    val timestamp: Long = System.currentTimeMillis(),
)

/** Live, observable snapshot of the current download. */
data class DownloadState(
    val status: JobStatus = JobStatus.IDLE,
    val novelId: String? = null,
    val title: String = "",
    val total: Int = 0,
    val completed: Int = 0,
    val skipped: Int = 0,
    val currentChapter: String = "",
    val epubFile: String? = null,
    val error: String? = null,
) {
    val percent: Float
        get() = if (total > 0) (completed.toFloat() / total.toFloat()) * 100f else 0f
}

/** A book entry shown on the library shelf. */
data class LibraryBook(
    val novelId: String,
    val meta: NovelMeta,
    val totalChapters: Int,
    val downloadedChapters: Int,
    val epubFilename: String?,
    val coverFile: String?,
    val lastModified: Long,
)

/** Token rotation strategy for the download run. */
enum class RotationMode { ROUND_ROBIN, RANDOM }

/** Parameters that drive a single download job. */
data class DownloadConfig(
    val novelId: String,
    val startChapter: Int? = null,
    val endChapter: Int? = null,
    val delayMin: Double = 2.0,
    val delayMax: Double = 6.0,
    val force: Boolean = false,
    val highlight: Boolean = false,
    val renumber: Boolean = false,
    val refreshIndex: Boolean = false,
    val shuffle: Boolean = true,
    val rotationMode: RotationMode = RotationMode.ROUND_ROBIN,
)
