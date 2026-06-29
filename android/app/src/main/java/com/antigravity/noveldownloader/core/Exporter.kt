package com.antigravity.noveldownloader.core

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** Handles compiling-on-demand, sharing, and saving EPUBs to public storage. */
object Exporter {

    /** Public folder (under the device's shared Downloads) where EPUBs are exported. */
    const val PUBLIC_SUBDIR = "Antigravity"
    const val PUBLIC_DISPLAY = "Download/Antigravity"

    /** Resolve the EPUB for a novel, compiling it from cache if it does not exist yet. */
    suspend fun resolveEpub(context: Context, novelId: String): File = withContext(Dispatchers.IO) {
        val cache = NovelCache(context)
        val info = cache.getBookInfo(novelId)
        val safeTitle = NovelCache.safeFilename(info?.title ?: "Novel $novelId", "Novel $novelId")
        val epub = File(cache.novelDir(novelId), "$safeTitle.epub")
        if (epub.exists()) return@withContext epub
        EpubBuilder(cache).compile(novelId)
    }

    fun shareIntent(context: Context, file: File): Intent {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        return Intent(Intent.ACTION_SEND).apply {
            type = "application/epub+zip"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    /**
     * Copy an EPUB into the public Downloads/Antigravity folder so it's visible to any
     * file manager and reading app. Returns a human-readable destination path.
     */
    suspend fun saveToDownloads(context: Context, file: File): String = withContext(Dispatchers.IO) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val resolver = context.contentResolver
            val relPath = "${Environment.DIRECTORY_DOWNLOADS}/$PUBLIC_SUBDIR"

            // Replace an existing copy so re-exports don't pile up "(1)" duplicates.
            resolver.delete(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                "${MediaStore.Downloads.DISPLAY_NAME}=? AND ${MediaStore.Downloads.RELATIVE_PATH}=?",
                arrayOf(file.name, "$relPath/")
            )

            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, file.name)
                put(MediaStore.Downloads.MIME_TYPE, "application/epub+zip")
                put(MediaStore.Downloads.RELATIVE_PATH, relPath)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Could not create a Downloads entry")
            resolver.openOutputStream(uri).use { out ->
                file.inputStream().use { input -> input.copyTo(out!!) }
            }
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            "$PUBLIC_DISPLAY/${file.name}"
        } else {
            val dir = File(
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                PUBLIC_SUBDIR
            )
            dir.mkdirs()
            val dest = File(dir, file.name)
            file.copyTo(dest, overwrite = true)
            dest.absolutePath
        }
    }

    /** Compile (if needed) then export to public Downloads. Returns the display path, or null on failure. */
    suspend fun autoExport(context: Context, novelId: String): String? = try {
        val file = resolveEpub(context, novelId)
        saveToDownloads(context, file)
    } catch (e: Exception) {
        null
    }
}
