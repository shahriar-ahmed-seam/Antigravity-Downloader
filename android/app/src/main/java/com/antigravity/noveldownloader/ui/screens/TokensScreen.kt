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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.antigravity.noveldownloader.core.TokenStore
import com.antigravity.noveldownloader.ui.AppViewModel
import com.antigravity.noveldownloader.ui.components.AppTextField
import com.antigravity.noveldownloader.ui.components.FieldLabel
import com.antigravity.noveldownloader.ui.components.PanelCard
import com.antigravity.noveldownloader.ui.components.Pill
import com.antigravity.noveldownloader.ui.components.SectionTitle
import com.antigravity.noveldownloader.ui.components.SharpButton
import com.antigravity.noveldownloader.ui.theme.AppColors
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun TokensScreen(vm: AppViewModel) {
    val tokens by vm.tokens.collectAsState()

    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        PanelCard {
            SectionTitle("Bearer Tokens", "Add as many as you like — the downloader rotates across them")
            Spacer(Modifier.height(14.dp))
            FieldLabel("Paste a token")
            Spacer(Modifier.height(6.dp))
            AppTextField(
                value = vm.newTokenInput,
                onValueChange = { vm.newTokenInput = it },
                placeholder = "Bearer eyJhbGc…",
                singleLine = false,
                mono = true,
            )
            Spacer(Modifier.height(12.dp))
            SharpButton("Add Token", { vm.addToken() }, Modifier.fillMaxWidth())
            Spacer(Modifier.height(10.dp))
            Text(
                "Capture from your browser: DevTools → Network → any gateway request → " +
                    "Headers → copy the full \"authorization\" value (incl. the Bearer prefix). " +
                    "Tokens are stored only on this device.",
                color = AppColors.TextDim,
                fontSize = 11.sp,
            )
        }

        if (tokens.isEmpty()) {
            PanelCard(background = AppColors.SurfaceAlt) {
                Text("No tokens stored. Add one above to enable downloads.", color = AppColors.TextMuted, fontSize = 13.sp)
            }
        }

        tokens.forEachIndexed { i, token ->
            val info = TokenStore.info(token)
            PanelCard(background = AppColors.SurfaceAlt) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("#${i + 1}  ${info.preview}", color = AppColors.TextMain, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (info.expired) {
                                Pill("Expired", AppColors.Danger)
                            } else {
                                Pill("Active", AppColors.Success)
                            }
                            info.expiresAt?.let {
                                val date = SimpleDateFormat("MMM d, HH:mm", Locale.getDefault()).format(Date(it * 1000))
                                Pill("exp $date", AppColors.PrimaryBright)
                            }
                        }
                    }
                    Spacer(Modifier.height(0.dp))
                    SharpButton("Remove", { vm.removeToken(token) }, color = AppColors.Danger)
                }
            }
        }
    }
}
