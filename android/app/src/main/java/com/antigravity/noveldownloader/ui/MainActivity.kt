package com.antigravity.noveldownloader.ui

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.antigravity.noveldownloader.core.JobStatus
import com.antigravity.noveldownloader.ui.components.HeroHeader
import com.antigravity.noveldownloader.ui.screens.ConsoleScreen
import com.antigravity.noveldownloader.ui.screens.DownloadScreen
import com.antigravity.noveldownloader.ui.screens.LibraryScreen
import com.antigravity.noveldownloader.ui.screens.TokensScreen
import com.antigravity.noveldownloader.ui.theme.AntigravityTheme
import com.antigravity.noveldownloader.ui.theme.AppColors

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
                .launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        setContent {
            AntigravityTheme {
                AppRoot()
            }
        }
    }
}

private val TABS = listOf("Download", "Console", "Library", "Tokens")

@Composable
fun AppRoot(vm: AppViewModel = viewModel()) {
    var showSplash by remember { mutableStateOf(true) }
    LaunchedEffect(Unit) {
        kotlinx.coroutines.delay(1500)
        showSplash = false
    }

    androidx.compose.animation.Crossfade(targetState = showSplash, label = "splash") { splash ->
        if (splash) {
            com.antigravity.noveldownloader.ui.components.SplashScreen()
        } else {
            MainShell(vm)
        }
    }
}

@Composable
private fun MainShell(vm: AppViewModel) {
    var tab by remember { mutableIntStateOf(0) }
    val snackHost = remember { SnackbarHostState() }
    val state by vm.downloadState.collectAsState()
    val tokens by vm.tokens.collectAsState()

    LaunchedEffect(vm.snackbar) {
        vm.snackbar?.let {
            snackHost.showSnackbar(it)
            vm.consumeSnackbar()
        }
    }
    // Surface token-expired prompts by hopping to the Tokens tab.
    LaunchedEffect(state.status) {
        if (state.status == JobStatus.TOKEN_EXPIRED) tab = 3
        if (state.status == JobStatus.COMPLETED) vm.refreshLibrary()
    }
    // Always re-scan when the Library tab is opened.
    LaunchedEffect(tab) {
        if (tab == 2) vm.refreshLibrary()
    }

    Scaffold(
        containerColor = AppColors.Background,
        snackbarHost = { SnackbarHost(snackHost) },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .background(AppColors.Background),
        ) {
            HeroHeader()
            TabBar(tab, tokens.size, state.status) { tab = it }

            Box(modifier = Modifier.padding(16.dp)) {
                when (tab) {
                    0 -> DownloadScreen(vm)
                    1 -> ConsoleScreen(vm)
                    2 -> LibraryScreen(vm)
                    else -> TokensScreen(vm)
                }
            }
        }
    }
}

@Composable
private fun TabBar(selected: Int, tokenCount: Int, status: JobStatus, onSelect: (Int) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(AppColors.SurfaceAlt),
    ) {
        TABS.forEachIndexed { i, label ->
            val active = i == selected
            val badge = when (i) {
                1 -> if (status == JobStatus.RUNNING) " ●" else ""
                3 -> if (tokenCount > 0) " ($tokenCount)" else ""
                else -> ""
            }
            Surface(
                modifier = Modifier.weight(1f),
                color = Color.Transparent,
                shape = RectangleShape,
                onClick = { onSelect(i) },
            ) {
                Column {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(if (active) AppColors.Primary else AppColors.Border)
                            .padding(top = if (active) 2.dp else 1.dp),
                    ) {}
                    Box(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 14.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = label + badge,
                            color = if (active) AppColors.TextMain else AppColors.TextMuted,
                            fontSize = 12.sp,
                            fontWeight = if (active) FontWeight.Bold else FontWeight.Medium,
                        )
                    }
                }
            }
        }
    }
}
