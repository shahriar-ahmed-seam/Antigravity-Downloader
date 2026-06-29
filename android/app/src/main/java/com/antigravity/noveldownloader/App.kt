package com.antigravity.noveldownloader

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import com.antigravity.noveldownloader.core.GatewayEngine

class App : Application() {

    override fun onCreate() {
        super.onCreate()
        createChannel()
        // Warm up the network engine early so the first request is fast.
        GatewayEngine.init(this)
    }

    private fun createChannel() {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.download_channel_name),
            NotificationManager.IMPORTANCE_LOW
        ).apply { description = getString(R.string.download_channel_desc) }
        mgr.createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL_ID = "novel_downloads"
    }
}
