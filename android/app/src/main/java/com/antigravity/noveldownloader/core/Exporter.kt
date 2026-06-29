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

    /** Copy the EPUB into the public Downloads collection. Returns a display path. */
    suspend fun saveToDownloads(context: Context, file: File): String = withContext(Dispatchers.IO) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, file.name)
                put(MediaStore.Downloads.MIME_TYPE, "application/epub+zip")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Could not create Downloads entry")
            resolver.openOutputStream(uri).use { out ->
                file.inputStream().use { input -> input.copyTo(out!!) }
            }
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            "Downloads/${file.name}"
        } else {
            val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            downloads.mkdirs()
            val dest = File(downloads, file.name)
            file.copyTo(dest, overwrite = true)
            dest.absolutePath
        }
    }
}
