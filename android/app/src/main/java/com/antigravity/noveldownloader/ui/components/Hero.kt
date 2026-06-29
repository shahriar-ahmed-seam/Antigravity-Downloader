package com.antigravity.noveldownloader.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.antigravity.noveldownloader.R
import com.antigravity.noveldownloader.ui.theme.AppColors

/** Brand banner: the logo mark over a layered indigo gradient. */
@Composable
fun HeroHeader(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(150.dp)
            .background(
                Brush.linearGradient(
                    listOf(Color(0xFF0B0D17), AppColors.PrimaryDim.copy(alpha = 0.45f), Color(0xFF0B0D17))
                )
            ),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Brush.verticalGradient(listOf(Color(0x22000000), Color(0xCC05060A))))
        )
        Row(
            modifier = Modifier
                .align(Alignment.CenterStart)
                .padding(horizontal = 24.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Image(
                painter = painterResource(R.drawable.logo),
                contentDescription = "Logo",
                modifier = Modifier.size(64.dp),
                contentScale = ContentScale.Fit,
            )
            Column {
                Text(
                    text = "ANTIGRAVITY",
                    color = AppColors.PrimaryBright,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 4.sp,
                )
                Text(
                    text = "Downloader",
                    color = Color.White,
                    fontSize = 30.sp,
                    fontWeight = FontWeight.Black,
                )
                Text(
                    text = "Gateway API · cache · EPUB",
                    color = AppColors.TextMuted,
                    fontSize = 12.sp,
                )
            }
        }
    }
}
