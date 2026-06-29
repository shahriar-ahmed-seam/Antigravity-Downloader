package com.antigravity.noveldownloader.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.antigravity.noveldownloader.App
import com.antigravity.noveldownloader.core.DownloadConfig
import com.antigravity.noveldownloader.core.DownloadController
import com.antigravity.noveldownloader.core.JobStatus
import com.antigravity.noveldownloader.core.RotationMode
import com.antigravity.noveldownloader.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * Foreground service that hosts a single download run so the OS keeps the
 * process (and the WebView engine) alive while the user is elsewhere.
 */
class DownloadService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var runJob: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                DownloadController.abort()
                stopForegroundCompat()
                stopSelf()
                return START_NOT_STICKY
            }
            else -> startRun(intent)
        }
        return START_NOT_STICKY
    }

    private fun startRun(intent: Intent?) {
        if (intent == null) { stopSelf(); return }
        if (DownloadController.isRunning) {
            startForegroundCompat(buildNotification("Downloading…", "A download is already running"))
            return
        }

        val novelId = intent.getStringExtra(EX_NOVEL_ID) ?: run { stopSelf(); return }
        val title = intent.getStringExtra(EX_TITLE).orEmpty()
        val tokens = intent.getStringArrayListExtra(EX_TOKENS) ?: arrayListOf()
        val config = DownloadConfig(
            novelId = novelId,
            startChapter = intent.getIntExtra(EX_START, -1).takeIf { it > 0 },
            endChapter = intent.getIntExtra(EX_END, -1).takeIf { it > 0 },
            delayMin = intent.getDoubleExtra(EX_DELAY_MIN, 2.0),
            delayMax = intent.getDoubleExtra(EX_DELAY_MAX, 6.0),
            force = intent.getBooleanExtra(EX_FORCE, false),
            highlight = intent.getBooleanExtra(EX_HIGHLIGHT, false),
            renumber = intent.getBooleanExtra(EX_RENUMBER, false),
            refreshIndex = intent.getBooleanExtra(EX_REFRESH, false),
            shuffle = intent.getBooleanExtra(EX_SHUFFLE, true),
            rotationMode = RotationMode.ROUND_ROBIN,
        )

        startForegroundCompat(buildNotification(title.ifBlank { "Novel $novelId" }, "Starting…"))

        // Keep the notification progress in sync with the controller state.
        scope.launch {
            DownloadController.state.collectLatest { st ->
                val text = when (st.status) {
                    JobStatus.RUNNING -> "${st.completed}/${st.total} • ${st.currentChapter.take(40)}"
                    JobStatus.PAUSED -> "Paused • ${st.completed}/${st.total}"
                    JobStatus.TOKEN_EXPIRED -> "Waiting for a valid token"
                    JobStatus.COMPLETED -> "Completed • ${st.epubFile}"
                    JobStatus.FAILED -> "Failed • ${st.error}"
                    JobStatus.ABORTED -> "Aborted"
                    JobStatus.IDLE -> "Idle"
                }
                notify(buildNotification(title.ifBlank { st.title }, text, st.percent.toInt(), st.total > 0 && st.status == JobStatus.RUNNING))
                if (st.status in setOf(JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.ABORTED)) {
                    stopForegroundCompat()
                    stopSelf()
                }
            }
        }

        runJob = scope.launch {
            DownloadController.run(applicationContext, config, tokens, title.ifBlank { "Novel $novelId" })
        }
    }

    private fun buildNotification(title: String, text: String, progress: Int = 0, showProgress: Boolean = false): Notification {
        val openIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val stopIntent = PendingIntent.getService(
            this, 1,
            Intent(this, DownloadService::class.java).apply { action = ACTION_STOP },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, App.CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(showProgress)
            .setOnlyAlertOnce(true)
            .setContentIntent(openIntent)
            .addAction(0, "Stop", stopIntent)
            .apply { if (showProgress) setProgress(100, progress.coerceIn(0, 100), false) }
            .build()
    }

    private fun notify(n: Notification) {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
        mgr.notify(NOTIF_ID, n)
    }

    private fun startForegroundCompat(n: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIF_ID, n)
        }
    }

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    companion object {
        private const val NOTIF_ID = 4201
        const val ACTION_STOP = "com.antigravity.noveldownloader.STOP"

        private const val EX_NOVEL_ID = "novel_id"
        private const val EX_TITLE = "title"
        private const val EX_TOKENS = "tokens"
        private const val EX_START = "start"
        private const val EX_END = "end"
        private const val EX_DELAY_MIN = "delay_min"
        private const val EX_DELAY_MAX = "delay_max"
        private const val EX_FORCE = "force"
        private const val EX_HIGHLIGHT = "highlight"
        private const val EX_RENUMBER = "renumber"
        private const val EX_REFRESH = "refresh"
        private const val EX_SHUFFLE = "shuffle"

        fun start(context: Context, config: DownloadConfig, tokens: List<String>, title: String) {
            val intent = Intent(context, DownloadService::class.java).apply {
                putExtra(EX_NOVEL_ID, config.novelId)
                putExtra(EX_TITLE, title)
                putStringArrayListExtra(EX_TOKENS, ArrayList(tokens))
                putExtra(EX_START, config.startChapter ?: -1)
                putExtra(EX_END, config.endChapter ?: -1)
                putExtra(EX_DELAY_MIN, config.delayMin)
                putExtra(EX_DELAY_MAX, config.delayMax)
                putExtra(EX_FORCE, config.force)
                putExtra(EX_HIGHLIGHT, config.highlight)
                putExtra(EX_RENUMBER, config.renumber)
                putExtra(EX_REFRESH, config.refreshIndex)
                putExtra(EX_SHUFFLE, config.shuffle)
            }
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
        }
    }
}
