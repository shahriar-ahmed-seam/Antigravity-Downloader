package com.antigravity.noveldownloader.core

import android.content.Context
import android.util.Base64
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import org.json.JSONObject

private val Context.tokenDataStore by preferencesDataStore(name = "antigravity_tokens")

/** A single bearer token plus a derived display fingerprint. */
data class TokenInfo(
    val raw: String,
    val expiresAt: Long?,
) {
    val preview: String
        get() {
            val clean = raw.removePrefix("Bearer ").trim()
            return if (clean.length <= 18) clean else "${clean.take(10)}…${clean.takeLast(6)}"
        }

    val expired: Boolean
        get() = expiresAt != null && System.currentTimeMillis() / 1000 > expiresAt
}

/**
 * Persists the user's list of bearer tokens. The user can add as many as they
 * want; the downloader rotates across them and skips any that the gateway rejects.
 */
class TokenStore(private val context: Context) {

    private val json = Json { ignoreUnknownKeys = true }
    private val key = stringPreferencesKey("tokens_json")

    val tokensFlow: Flow<List<String>> = context.tokenDataStore.data.map { prefs ->
        decode(prefs[key])
    }

    suspend fun getTokens(): List<String> = decode(context.tokenDataStore.data.first()[key])

    suspend fun addToken(raw: String) {
        val norm = normalize(raw)
        if (norm.isBlank()) return
        val current = getTokens().toMutableList()
        if (current.none { it == norm }) {
            current.add(norm)
            persist(current)
        }
    }

    suspend fun removeToken(raw: String) {
        val current = getTokens().toMutableList()
        current.removeAll { it == raw }
        persist(current)
    }

    suspend fun clear() = persist(emptyList())

    private suspend fun persist(list: List<String>) {
        context.tokenDataStore.edit { it[key] = json.encodeToString(ListSerializer(String.serializer()), list) }
    }

    private fun decode(value: String?): List<String> {
        if (value.isNullOrBlank()) return emptyList()
        return try {
            json.decodeFromString(ListSerializer(String.serializer()), value)
        } catch (_: Exception) {
            emptyList()
        }
    }

    companion object {
        fun normalize(raw: String): String {
            val t = raw.trim()
            if (t.isEmpty()) return ""
            return if (t.startsWith("Bearer ")) t else "Bearer $t"
        }

        /** Decode the `exp` claim (unix seconds) from a JWT, or null. */
        fun decodeExpiry(token: String): Long? {
            return try {
                val clean = token.removePrefix("Bearer ").trim()
                val parts = clean.split(".")
                if (parts.size != 3) return null
                var b64 = parts[1]
                val pad = (4 - b64.length % 4) % 4
                b64 += "=".repeat(pad)
                val payload = String(Base64.decode(b64, Base64.URL_SAFE))
                val exp = JSONObject(payload).optLong("exp", -1L)
                if (exp <= 0) null else exp
            } catch (_: Exception) {
                null
            }
        }

        fun info(token: String): TokenInfo = TokenInfo(token, decodeExpiry(token))
    }
}
