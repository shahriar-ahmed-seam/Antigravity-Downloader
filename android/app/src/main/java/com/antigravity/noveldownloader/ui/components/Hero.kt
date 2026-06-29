package com.antigravity.noveldownloader.ui.components

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.antigravity.noveldownloader.ui.theme.AppColors

/**
 * Hero banner. Drop your own image into `app/src/main/assets/` named
 * `hero.jpg`, `hero.png` or `hero.webp` and it will be used automatically.
 * If none is present, a layered indigo gradient is shown instead.
 */
@Composable
fun HeroHeader(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val bitmap by produceState<ImageBitmap?>(initialValue = null) {
        value = runCatching {
            val candidates = listOf("hero.jpg", "hero.jpeg", "hero.png", "hero.webp")
            val names = context.assets.list("")?.toSet() ?: emptySet()
            val pick = candidates.firstOrNull { it in names } ?: return@runCatching null
            context.assets.open(pick).use { BitmapFactory.decodeStream(it)?.asImageBitmap() }
        }.getOrNull()
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(190.dp)
            .background(
                Brush.linearGradient(
                    listOf(Color(0xFF0B0D17), AppColors.PrimaryDim.copy(alpha = 0.55f), Color(0xFF0B0D17))
                )
            ),
    ) {
        bitmap?.let {
            Image(
                bitmap = it,
                contentDescription = "Hero",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
            )
        }
        // Legibility scrim.
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        listOf(Color(0x33000000), Color(0xCC05060A))
                    )
                )
        )
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(24.dp),
        ) {
            Text(
                text = "ANTIGRAVITY",
                color = AppColors.PrimaryBright,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 4.sp,
            )
            Text(
                text = "Novel Downloader",
                color = Color.White,
                fontSize = 30.sp,
                fontWeight = FontWeight.Black,
            )
            Text(
                text = "Scrape · cache · compile to EPUB",
                color = AppColors.TextMuted,
                fontSize = 13.sp,
            )
        }
    }
}
