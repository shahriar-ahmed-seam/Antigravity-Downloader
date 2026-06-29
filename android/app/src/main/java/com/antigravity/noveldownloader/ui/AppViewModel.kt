package com.antigravity.noveldownloader.ui

import android.app.Application
import android.content.Intent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.antigravity.noveldownloader.core.AnalyzeResult
import com.antigravity.noveldownloader.core.DownloadConfig
import com.antigravity.noveldownloader.core.DownloadController
import com.antigravity.noveldownloader.core.Exporter
import com.antigravity.noveldownloader.core.LibraryBook
import com.antigravity.noveldownloader.core.NovelAnalyzer
import com.antigravity.noveldownloader.core.NovelCache
import com.antigravity.noveldownloader.core.NovelMeta
import com.antigravity.noveldownloader.core.TokenStore
import com.antigravity.noveldownloader.service.DownloadService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val tokenStore = TokenStore(app)
    private val cache = NovelCache(app)
    private val analyzer = NovelAnalyzer(app)

    val tokens: StateFlow<List<String>> = tokenStore.tokensFlow
        .stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    private val _library = MutableStateFlow<List<LibraryBook>>(emptyList())
    val library: StateFlow<List<LibraryBook>> = _library

    val downloadState = DownloadController.state
    val logs = DownloadController.logs

    // --- Form inputs ---
    var url by mutableStateOf("")
    var novelIdOverride by mutableStateOf("")
    var startChapter by mutableStateOf("1")
    var endChapter by mutableStateOf("")
    var delayMin by mutableStateOf("3")
    var delayMax by mutableStateOf("8")
    var renumber by mutableStateOf(false)
    var highlight by mutableStateOf(false)
    var force by mutableStateOf(false)
    var refreshIndex by mutableStateOf(false)
    var shuffle by mutableStateOf(true)

    var analyzing by mutableStateOf(false)
    var analyzedMeta by mutableStateOf<NovelMeta?>(null)
    var totalChapters by mutableStateOf(0)

    var snackbar by mutableStateOf<String?>(null)
    var newTokenInput by mutableStateOf("")

    init {
        refreshLibrary()
    }

    fun consumeSnackbar() { snackbar = null }

    // --- Tokens ---
    fun addToken() {
        val raw = newTokenInput.trim()
        if (raw.isEmpty()) { snackbar = "Paste a token first."; return }
        viewModelScope.launch {
            tokenStore.addToken(raw)
            newTokenInput = ""
            if (DownloadController.isRunning) DownloadController.notifyTokensUpdated(tokenStore.getTokens())
            snackbar = "Token added."
        }
    }

    fun removeToken(token: String) {
        viewModelScope.launch {
            tokenStore.removeToken(token)
            if (DownloadController.isRunning) DownloadController.notifyTokensUpdated(tokenStore.getTokens())
        }
    }

    // --- Analyze ---
    fun analyze() {
        if (analyzing) return
        val u = url.trim()
        if (!u.contains("fictionzone.net/novel/")) { snackbar = "Enter a valid fictionzone.net/novel/ URL."; return }
        analyzing = true
        viewModelScope.launch {
            val result = analyzer.analyze(u, novelIdOverride.trim().ifBlank { null }, tokens.value)
            analyzing = false
            result.onSuccess { res: AnalyzeResult ->
                analyzedMeta = res.meta
                totalChapters = res.chapters.size
                if (endChapter.isBlank() && res.chapters.isNotEmpty()) {
                    endChapter = res.chapters.size.toString()
                }
                refreshLibrary()
                snackbar = "Loaded \"${res.meta.title}\" (${res.chapters.size} chapters)."
            }.onFailure { e ->
                snackbar = e.message ?: "Analyze failed."
            }
        }
    }

    // --- Download ---
    fun startDownload() {
        val meta = analyzedMeta ?: run { snackbar = "Analyze a novel first."; return }
        val toks = tokens.value
        if (toks.isEmpty()) { snackbar = "Add at least one bearer token."; return }
        if (DownloadController.isRunning) { snackbar = "A download is already running."; return }

        val dMin = delayMin.toDoubleOrNull() ?: 3.0
        val dMax = delayMax.toDoubleOrNull() ?: 8.0
        val config = DownloadConfig(
            novelId = meta.novelId,
            startChapter = startChapter.toIntOrNull()?.takeIf { it > 0 },
            endChapter = endChapter.toIntOrNull()?.takeIf { it > 0 },
            delayMin = dMin,
            delayMax = dMax,
            force = force,
            highlight = highlight,
            renumber = renumber,
            refreshIndex = refreshIndex,
            shuffle = shuffle,
        )
        DownloadController.clearLogs()
        DownloadService.start(getApplication(), config, toks, meta.title)
        snackbar = "Download started."
    }

    fun pause() = DownloadController.pause()
    fun resume() = DownloadController.resume()
    fun clearLogsAction() = DownloadController.clearLogs()
    fun abort() {
        val ctx = getApplication<Application>()
        ctx.startService(Intent(ctx, DownloadService::class.java).apply { action = DownloadService.ACTION_STOP })
    }

    // --- Library ---
    fun refreshLibrary() {
        viewModelScope.launch {
            val books = withContext(Dispatchers.IO) { cache.listBooks() }
            _library.value = books
        }
    }

    fun deleteBook(novelId: String) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { cache.deleteBook(novelId) }
            refreshLibrary()
            snackbar = "Deleted."
        }
    }

    fun shareEpub(novelId: String) {
        viewModelScope.launch {
            try {
                val file = Exporter.resolveEpub(getApplication(), novelId)
                val intent = Exporter.shareIntent(getApplication(), file)
                val chooser = Intent.createChooser(intent, "Share EPUB").apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                getApplication<Application>().startActivity(chooser)
            } catch (e: Exception) {
                snackbar = e.message ?: "Could not share EPUB."
            }
        }
    }

    fun saveEpub(novelId: String) {
        viewModelScope.launch {
            try {
                val file = Exporter.resolveEpub(getApplication(), novelId)
                val path = Exporter.saveToDownloads(getApplication(), file)
                snackbar = "Saved to $path"
            } catch (e: Exception) {
                snackbar = e.message ?: "Could not save EPUB."
            }
        }
    }

    fun recompile(novelId: String) {
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { com.antigravity.noveldownloader.core.EpubBuilder(cache).compile(novelId) }
                refreshLibrary()
                snackbar = "Recompiled EPUB."
            } catch (e: Exception) {
                snackbar = e.message ?: "Recompile failed."
            }
        }
    }
}
