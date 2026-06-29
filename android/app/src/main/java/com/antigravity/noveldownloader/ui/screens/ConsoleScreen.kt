package com.antigravity.noveldownloader.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.antigravity.noveldownloader.core.JobStatus
import com.antigravity.noveldownloader.ui.AppViewModel
import com.antigravity.noveldownloader.ui.components.PanelCard
import com.antigravity.noveldownloader.ui.components.Pill
import com.antigravity.noveldownloader.ui.components.SectionTitle
import com.antigravity.noveldownloader.ui.components.SharpButton
import com.antigravity.noveldownloader.ui.theme.AppColors

@Composable
fun ConsoleScreen(vm: AppViewModel) {
    val state by vm.downloadState.collectAsState()
    val logs by vm.logs.collectAsState()

    val statusColor = when (state.status) {
        JobStatus.RUNNING -> AppColors.Success
        JobStatus.PAUSED -> AppColors.Warning
        JobStatus.TOKEN_EXPIRED -> AppColors.Warning
        JobStatus.COMPLETED -> AppColors.Success
        JobStatus.FAILED -> AppColors.Danger
        JobStatus.ABORTED -> AppColors.Danger
        JobStatus.IDLE -> AppColors.TextDim
    }

    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        PanelCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    SectionTitle("Live Console", "Real-time gateway progress")
                }
                Pill(state.status.name, statusColor)
            }

            Spacer(Modifier.height(16.dp))

            // Progress bar.
            val pct = state.percent.coerceIn(0f, 100f)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(22.dp)
                    .background(AppColors.ConsoleBg, RectangleShape),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(pct / 100f)
                        .height(22.dp)
                        .background(AppColors.Primary, RectangleShape),
                )
                Box(Modifier.fillMaxWidth().height(22.dp), contentAlignment = Alignment.Center) {
                    Text("${pct.toInt()}%", color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            }

            Spacer(Modifier.height(10.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Metric("Fetched", "${state.completed} / ${state.total}")
                Metric("Cached", state.skipped.toString())
                Metric("Status", state.status.name)
            }

            if (state.currentChapter.isNotBlank()) {
                Spacer(Modifier.height(8.dp))
                Text(state.currentChapter, color = AppColors.PrimaryBright, fontSize = 12.sp, maxLines = 1)
            }
            state.savedPath?.let {
                Spacer(Modifier.height(10.dp))
                Surface(color = AppColors.Success.copy(alpha = 0.12f)) {
                    Column(Modifier.padding(12.dp)) {
                        Text("EPUB SAVED TO", color = AppColors.Success, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                        Spacer(Modifier.height(2.dp))
                        Text(it, color = AppColors.TextMain, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                    }
                }
            }
            state.error?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = AppColors.Danger, fontSize = 12.sp)
            }

            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                when (state.status) {
                    JobStatus.RUNNING -> {
                        SharpButton("Pause", { vm.pause() }, Modifier.weight(1f), color = AppColors.Warning)
                        SharpButton("Stop", { vm.abort() }, Modifier.weight(1f), color = AppColors.Danger)
                    }
                    JobStatus.PAUSED, JobStatus.TOKEN_EXPIRED -> {
                        SharpButton("Resume", { vm.resume() }, Modifier.weight(1f), color = AppColors.Success)
                        SharpButton("Stop", { vm.abort() }, Modifier.weight(1f), color = AppColors.Danger)
                    }
                    else -> {
                        SharpButton("Clear Logs", { vm.clearLogsAction() }, Modifier.weight(1f), color = AppColors.Elevated, textColor = AppColors.TextMuted)
                    }
                }
            }
        }

        PanelCard(background = AppColors.ConsoleBg) {
            SectionTitle("Logs")
            Spacer(Modifier.height(10.dp))
            val scroll = rememberScrollState()
            LaunchedEffect(logs.size) { scroll.animateScrollTo(scroll.maxValue) }
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(360.dp)
                    .verticalScroll(scroll),
                verticalArrangement = Arrangement.spacedBy(3.dp),
            ) {
                if (logs.isEmpty()) {
                    Text("Waiting to initialise a download job…", color = AppColors.TextDim, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                }
                logs.forEach { line ->
                    val c = when (line.level) {
                        "success" -> AppColors.Success
                        "warn" -> AppColors.Warning
                        "error" -> AppColors.Danger
                        else -> AppColors.PrimaryBright
                    }
                    Text(line.message, color = c, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
                }
            }
        }
    }
}

@Composable
private fun Metric(label: String, value: String) {
    Column {
        Text(label.uppercase(), color = AppColors.TextDim, fontSize = 9.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = AppColors.TextMain, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
    }
}
