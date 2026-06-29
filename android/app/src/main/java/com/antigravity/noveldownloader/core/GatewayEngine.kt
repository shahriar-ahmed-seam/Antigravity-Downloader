package com.antigravity.noveldownloader.core

import android.annotation.SuppressLint
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

/**
 * Offscreen WebView used as the network engine.
 *
 * Why a WebView instead of OkHttp: fictionzone.net sits behind Cloudflare, which
 * fingerprints the TLS ClientHello. The proven Python pipeline only works because
 * `curl_cffi` impersonates Chrome's fingerprint. A WebView runs the real Chromium
 * network stack on-device, so `fetch()` calls made from the loaded fictionzone.net
 * page carry a genuine Chrome fingerprint, correct same-origin headers, and any
 * Cloudflare clearance cookies automatically. This mirrors the working pipeline
 * exactly without re-implementing TLS impersonation.
 */
object GatewayEngine {

    const val SITE_ORIGIN = "https://fictionzone.net"
    const val GATEWAY_URL = "$SITE_ORIGIN/api/__api_party/fictionzone"

    private val main = Handler(Looper.getMainLooper())
    private val json = Json { ignoreUnknownKeys = true }

    @SuppressLint("StaticFieldLeak")
    private var webView: WebView? = null
    private var ready = CompletableDeferred<Boolean>()

    private val pending = ConcurrentHashMap<String, CompletableDeferred<GatewayResult>>()
    private val counter = AtomicLong(0)

    @SuppressLint("SetJavaScriptEnabled")
    fun init(context: Context) {
        if (webView != null) return
        main.post {
            if (webView != null) return@post
            val wv = WebView(context.applicationContext)
            wv.settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                userAgentString = userAgentString.replace("; wv", "")
            }
            wv.addJavascriptInterface(Bridge(), "AndroidBridge")
            wv.webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    if (!ready.isCompleted) ready.complete(true)
                }
            }
            webView = wv
            wv.loadUrl("$SITE_ORIGIN/")
        }
    }

    /** Suspends until the warm-up page has loaded at least once. */
    suspend fun awaitReady(timeoutMs: Long = 45_000): Boolean {
        return withTimeoutOrNull(timeoutMs) { ready.await() } ?: false
    }

    private fun nowIso(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date())
    }

    private fun jsLiteral(value: String): String = json.encodeToString(JsonPrimitive.serializer(), JsonPrimitive(value))

    private fun runJs(script: String) {
        main.post { webView?.evaluateJavascript(script, null) }
    }

    /**
     * Perform the outer POST to the gateway with the inner routing envelope.
     * The bearer [token] is placed inside the envelope's authorization header,
     * exactly like the reference pipeline.
     */
    suspend fun postGateway(path: String, query: Map<String, Any?>, token: String, timeoutMs: Long = 30_000): GatewayResult {
        val normToken = if (token.isNotBlank() && !token.startsWith("Bearer ")) "Bearer $token" else token
        val envelope = buildJsonObject {
            put("path", path)
            put("method", "GET")
            put("query", buildJsonObject {
                for ((k, v) in query) {
                    when (v) {
                        is Boolean -> put(k, v)
                        is Int -> put(k, v)
                        is Long -> put(k, v)
                        null -> put(k, JsonPrimitive(null as String?))
                        else -> put(k, v.toString())
                    }
                }
            })
            put("headers", buildJsonArray {
                add(buildJsonArray { add("authorization"); add(normToken) })
                add(buildJsonArray { add("x-request-time"); add(nowIso()) })
            })
        }
        val bodyStr = envelope.toString()
        return fetchText(GATEWAY_URL, method = "POST", body = bodyStr, timeoutMs = timeoutMs)
    }

    /** GET a same-origin HTML page through the Chromium stack. */
    suspend fun getHtml(url: String, timeoutMs: Long = 30_000): GatewayResult =
        fetchText(url, method = "GET", body = null, timeoutMs = timeoutMs)

    private suspend fun fetchText(url: String, method: String, body: String?, timeoutMs: Long): GatewayResult {
        if (!awaitReady()) return GatewayResult(false, 0, "", "Engine warm-up timed out")
        val id = "r${counter.incrementAndGet()}"
        val deferred = CompletableDeferred<GatewayResult>()
        pending[id] = deferred

        val optsBody = if (body != null) ", body: ${jsLiteral(body)}" else ""
        val headers = if (method == "POST")
            "{'content-type':'application/json','accept':'application/json'}"
        else
            "{'accept':'text/html,application/xhtml+xml,application/json,*/*'}"

        val script = """
            (function(){
              try {
                fetch(${jsLiteral(url)}, {method:'$method', headers:$headers, credentials:'include'$optsBody})
                  .then(function(resp){ return resp.text().then(function(t){ AndroidBridge.onResult('$id', resp.status, t); }); })
                  .catch(function(e){ AndroidBridge.onError('$id', ''+e); });
              } catch(err) { AndroidBridge.onError('$id', ''+err); }
            })();
        """.trimIndent()
        runJs(script)

        val result = withTimeoutOrNull(timeoutMs) { deferred.await() }
        pending.remove(id)
        return result ?: GatewayResult(false, 0, "", "Request timed out")
    }

    /**
     * Download binary bytes (cover image). Covers live on a separate CDN that is
     * not gated by the Cloudflare JS/TLS challenge, so a plain connection is fine
     * and avoids cross-origin fetch/CORS limitations inside the WebView.
     */
    suspend fun getBytes(url: String, timeoutMs: Int = 20_000): ByteArray? = withContext(Dispatchers.IO) {
        try {
            val conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                setRequestProperty(
                    "User-Agent",
                    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) " +
                        "Chrome/120.0.0.0 Mobile Safari/537.36"
                )
                setRequestProperty("Referer", "$SITE_ORIGIN/")
            }
            conn.inputStream.use { it.readBytes() }
        } catch (e: Exception) {
            null
        }
    }

    @Suppress("unused")
    private class Bridge {
        @JavascriptInterface
        fun onResult(id: String, status: Int, body: String) {
            pending[id]?.complete(GatewayResult(ok = status in 200..299, status = status, body = body))
        }

        @JavascriptInterface
        fun onError(id: String, error: String) {
            pending[id]?.complete(GatewayResult(ok = false, status = 0, body = "", error = error))
        }
    }

    // Kept for potential future use: decode a data: URL body to bytes.
    fun decodeDataUrl(dataUrl: String): ByteArray? {
        val comma = dataUrl.indexOf(',')
        if (comma < 0) return null
        return try {
            Base64.decode(dataUrl.substring(comma + 1), Base64.DEFAULT)
        } catch (e: Exception) {
            null
        }
    }
}
