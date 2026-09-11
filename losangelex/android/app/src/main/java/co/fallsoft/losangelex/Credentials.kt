package co.fallsoft.losangelex

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** A captured host and credential pair; requests retain it across connection changes. */
class HostConnection(val url: String, internal val token: String)

/** Device-local credentials encrypted by an Android Keystore key; backups are disabled. */
class Credentials(context: Context) {
    private val preferences = context.getSharedPreferences("connection", Context.MODE_PRIVATE)
    private val alias = "losangelex-room-token"
    val url: String
        get() = preferences.getString("url", "") ?: ""

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
            generateKey()
        }
    }

    fun read(): HostConnection {
        val saved = preferences.all
        val host = saved["url"] as? String ?: ""
        val encoded = saved["token"] as? String ?: return HostConnection(host, "")
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val token = Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            String(doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
        }
        return HostConnection(host, token)
    }

    fun connect(url: String, token: String) {
        val encrypted = Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.ENCRYPT_MODE, key())
            iv + doFinal(token.toByteArray(Charsets.UTF_8))
        }
        check(preferences.edit().putString("url", url.trimEnd('/'))
            .putString("token", Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit())
    }
}
