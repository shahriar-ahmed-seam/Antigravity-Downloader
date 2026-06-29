package com.antigravity.noveldownloader.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

// Palette carried over from the reference web UI (indigo on near-black).
object AppColors {
    val Background = Color(0xFF090A0F)
    val Surface = Color(0xFF121420)
    val SurfaceAlt = Color(0xFF0E1018)
    val Elevated = Color(0xFF181B29)
    val Border = Color(0xFF23273A)
    val BorderStrong = Color(0xFF2E3350)

    val Primary = Color(0xFF6366F1)
    val PrimaryBright = Color(0xFF818CF8)
    val PrimaryDim = Color(0xFF4F46E5)

    val Success = Color(0xFF10B981)
    val Warning = Color(0xFFF59E0B)
    val Danger = Color(0xFFEF4444)

    val TextMain = Color(0xFFF3F4F6)
    val TextMuted = Color(0xFF9CA3AF)
    val TextDim = Color(0xFF6B7280)

    val ConsoleBg = Color(0xFF05060A)
}

private val DarkScheme = darkColorScheme(
    primary = AppColors.Primary,
    onPrimary = Color.White,
    secondary = AppColors.PrimaryBright,
    background = AppColors.Background,
    onBackground = AppColors.TextMain,
    surface = AppColors.Surface,
    onSurface = AppColors.TextMain,
    surfaceVariant = AppColors.Elevated,
    onSurfaceVariant = AppColors.TextMuted,
    error = AppColors.Danger,
    outline = AppColors.Border,
)

// Every corner is square — a hard product requirement.
private val SquareShapes = Shapes(
    extraSmall = RoundedCornerShape(0.dp),
    small = RoundedCornerShape(0.dp),
    medium = RoundedCornerShape(0.dp),
    large = RoundedCornerShape(0.dp),
    extraLarge = RoundedCornerShape(0.dp),
)

@Composable
fun AntigravityTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkScheme,
        shapes = SquareShapes,
        typography = Typography(),
        content = content,
    )
}
