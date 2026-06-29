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
import com.antigravity.noveldownloader.ui.components.PanelCard
import com.antigravity.noveldownloader.ui.components.Pill
import com.antigravity.noveldownloader.ui.components.SectionTitle
import com.antigravity.noveldownloader.ui.components.SharpButton
import com.antigravity.noveldownloader.ui.theme.AppColors

@Composable
fun LibraryScreen(vm: AppViewModel) {
    val books by vm.library.collectAsState()

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        PanelCard {
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    SectionTitle("Library Shelf", "Manage downloads, recompile, export")
                }
                SharpButton("Refresh", { vm.refreshLibrary(announce = true) }, color = AppColors.Elevated, textColor = AppColors.TextMuted)
            }
        }

        if (books.isEmpty()) {
            PanelCard(background = AppColors.SurfaceAlt) {
                Text(
                    "Your shelf is empty. Analyze and download a novel to get started.",
                    color = AppColors.TextMuted,
                    fontSize = 13.sp,
                )
            }
        }

        books.forEach { book ->
            PanelCard(background = AppColors.SurfaceAlt) {
                Text(book.meta.title, color = AppColors.TextMain, fontSize = 16.sp, fontWeight = FontWeight.Bold, maxLines = 2)
                Spacer(Modifier.height(2.dp))
                Text("by ${book.meta.author}", color = AppColors.TextMuted, fontSize = 12.sp)
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Pill("ID ${book.novelId}", AppColors.PrimaryBright)
                    Pill("${book.downloadedChapters}/${book.totalChapters} ch", AppColors.Success)
                    if (book.epubFilename != null) Pill("EPUB", AppColors.Primary)
                }

                Spacer(Modifier.height(14.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    SharpButton("Save", { vm.saveEpub(book.novelId) }, Modifier.weight(1f), color = AppColors.Success)
                    SharpButton("Share", { vm.shareEpub(book.novelId) }, Modifier.weight(1f), color = AppColors.Primary)
                }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    SharpButton("Recompile", { vm.recompile(book.novelId) }, Modifier.weight(1f), color = AppColors.Elevated, textColor = AppColors.TextMuted)
                    SharpButton("Delete", { vm.deleteBook(book.novelId) }, Modifier.weight(1f), color = AppColors.Danger)
                }
            }
        }

        // Storage info footer.
        Text(
            "Exported EPUBs → ${vm.exportLocation()}/",
            color = AppColors.TextMuted,
            fontSize = 11.sp,
            modifier = Modifier.padding(horizontal = 4.dp, vertical = 2.dp),
        )
        Text(
            "Cache: ${vm.booksLocation()}",
            color = AppColors.TextDim,
            fontSize = 10.sp,
            modifier = Modifier.padding(horizontal = 4.dp),
        )
    }
}
