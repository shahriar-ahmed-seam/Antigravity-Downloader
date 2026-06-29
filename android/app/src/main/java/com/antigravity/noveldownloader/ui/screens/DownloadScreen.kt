package com.antigravity.noveldownloader.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.antigravity.noveldownloader.ui.AppViewModel
import com.antigravity.noveldownloader.ui.components.AppTextField
import com.antigravity.noveldownloader.ui.components.FieldLabel
import com.antigravity.noveldownloader.ui.components.PanelCard
import com.antigravity.noveldownloader.ui.components.Pill
import com.antigravity.noveldownloader.ui.components.SectionTitle
import com.antigravity.noveldownloader.ui.components.SharpButton
import com.antigravity.noveldownloader.ui.components.ToggleRow
import com.antigravity.noveldownloader.ui.theme.AppColors

@Composable
fun DownloadScreen(vm: AppViewModel) {
    val tokens by vm.tokens.collectAsState()

    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        PanelCard {
            SectionTitle("Download a Novel", "Extract, fetch, cache and compile to EPUB")
            Spacer(Modifier.height(16.dp))

            FieldLabel("Novel landing URL")
            Spacer(Modifier.height(6.dp))
            AppTextField(vm.url, { vm.url = it }, "https://fictionzone.net/novel/slug-here")

            Spacer(Modifier.height(12.dp))
            FieldLabel("Novel ID — optional override")
            Spacer(Modifier.height(6.dp))
            AppTextField(vm.novelIdOverride, { vm.novelIdOverride = it }, "Auto-detected if left blank")

            Spacer(Modifier.height(16.dp))
            SharpButton(
                text = if (vm.analyzing) "Analyzing…" else "Analyze Novel",
                onClick = { vm.analyze() },
                enabled = !vm.analyzing,
                modifier = Modifier.fillMaxWidth(),
            )

            if (tokens.isEmpty()) {
                Spacer(Modifier.height(10.dp))
                Text(
                    "No tokens yet — add one in the Tokens tab before downloading.",
                    color = AppColors.Warning,
                    fontSize = 12.sp,
                )
            }
        }

        val meta = vm.analyzedMeta
        if (meta != null) {
            PanelCard(background = AppColors.SurfaceAlt) {
                Row {
                    Column(Modifier.weight(1f)) {
                        Text(meta.title, color = AppColors.TextMain, fontSize = 17.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(2.dp))
                        Text("by ${meta.author}", color = AppColors.TextMuted, fontSize = 12.sp)
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Pill("ID ${meta.novelId}", AppColors.PrimaryBright)
                            Pill("${vm.totalChapters} chapters", AppColors.Success)
                        }
                    }
                }

                Spacer(Modifier.height(16.dp))
                FieldLabel("Chapter range")
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text("Start", color = AppColors.TextMuted, fontSize = 11.sp)
                        Spacer(Modifier.height(4.dp))
                        AppTextField(vm.startChapter, { vm.startChapter = it.filter(Char::isDigit) })
                    }
                    Column(Modifier.weight(1f)) {
                        Text("End", color = AppColors.TextMuted, fontSize = 11.sp)
                        Spacer(Modifier.height(4.dp))
                        AppTextField(vm.endChapter, { vm.endChapter = it.filter(Char::isDigit) })
                    }
                }

                Spacer(Modifier.height(12.dp))
                FieldLabel("Random delay window (seconds)")
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text("Min", color = AppColors.TextMuted, fontSize = 11.sp)
                        Spacer(Modifier.height(4.dp))
                        AppTextField(vm.delayMin, { vm.delayMin = it.filter { c -> c.isDigit() || c == '.' } })
                    }
                    Column(Modifier.weight(1f)) {
                        Text("Max", color = AppColors.TextMuted, fontSize = 11.sp)
                        Spacer(Modifier.height(4.dp))
                        AppTextField(vm.delayMax, { vm.delayMax = it.filter { c -> c.isDigit() || c == '.' } })
                    }
                }

                Spacer(Modifier.height(14.dp))
                FieldLabel("Options")
                Spacer(Modifier.height(4.dp))
                ToggleRow("Shuffle fetch order (recommended)", vm.shuffle) { vm.shuffle = it }
                ToggleRow("Renumber chapters 1..N", vm.renumber) { vm.renumber = it }
                ToggleRow("Enable highlights", vm.highlight) { vm.highlight = it }
                ToggleRow("Ignore cache (redownload all)", vm.force) { vm.force = it }
                ToggleRow("Refresh chapter index", vm.refreshIndex) { vm.refreshIndex = it }

                Spacer(Modifier.height(16.dp))
                SharpButton(
                    text = "Start Download",
                    onClick = { vm.startDownload() },
                    color = AppColors.Success,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}
