package com.antigravity.noveldownloader.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.antigravity.noveldownloader.ui.theme.AppColors

@Composable
fun PanelCard(
    modifier: Modifier = Modifier,
    background: Color = AppColors.Surface,
    content: @Composable () -> Unit,
) {
    Surface(
        modifier = modifier,
        shape = RectangleShape,
        color = background,
        border = BorderStroke(1.dp, AppColors.Border),
    ) {
        Column(modifier = Modifier.padding(20.dp)) { content() }
    }
}

@Composable
fun SectionTitle(title: String, subtitle: String? = null) {
    Column {
        Text(
            text = title,
            color = AppColors.TextMain,
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold,
        )
        if (subtitle != null) {
            Text(text = subtitle, color = AppColors.TextMuted, fontSize = 12.sp)
        }
    }
}

@Composable
fun FieldLabel(text: String) {
    Text(
        text = text.uppercase(),
        color = AppColors.TextMuted,
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 1.sp,
    )
}

@Composable
fun AppTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String = "",
    modifier: Modifier = Modifier,
    singleLine: Boolean = true,
    mono: Boolean = false,
) {
    TextField(
        value = value,
        onValueChange = onValueChange,
        placeholder = { Text(placeholder, color = AppColors.TextDim, fontSize = 14.sp) },
        modifier = modifier.fillMaxWidth(),
        singleLine = singleLine,
        shape = RectangleShape,
        textStyle = androidx.compose.ui.text.TextStyle(
            color = AppColors.TextMain,
            fontSize = 14.sp,
            fontFamily = if (mono) FontFamily.Monospace else FontFamily.Default,
        ),
        colors = TextFieldDefaults.colors(
            focusedContainerColor = AppColors.SurfaceAlt,
            unfocusedContainerColor = AppColors.SurfaceAlt,
            disabledContainerColor = AppColors.SurfaceAlt,
            cursorColor = AppColors.Primary,
            focusedIndicatorColor = AppColors.Primary,
            unfocusedIndicatorColor = AppColors.Border,
        ),
    )
}

@Composable
fun SharpButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    color: Color = AppColors.Primary,
    textColor: Color = Color.White,
) {
    val bg = if (enabled) color else AppColors.Elevated
    Surface(
        modifier = modifier,
        shape = RectangleShape,
        color = bg,
        onClick = { if (enabled) onClick() },
        enabled = enabled,
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().padding(vertical = 14.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = text.uppercase(),
                color = if (enabled) textColor else AppColors.TextDim,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
fun ToggleRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Checkbox(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = CheckboxDefaults.colors(
                checkedColor = AppColors.Primary,
                uncheckedColor = AppColors.BorderStrong,
                checkmarkColor = Color.White,
            ),
            modifier = Modifier.size(36.dp),
        )
        Text(label, color = AppColors.TextMuted, fontSize = 13.sp)
    }
}

@Composable
fun Pill(text: String, color: Color, modifier: Modifier = Modifier) {
    Surface(shape = RectangleShape, color = color.copy(alpha = 0.16f), modifier = modifier) {
        Text(
            text = text.uppercase(),
            color = color,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 0.8.sp,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
        )
    }
}

@Composable
fun Dot(color: Color) {
    Box(modifier = Modifier.size(8.dp).background(color, RectangleShape))
}
