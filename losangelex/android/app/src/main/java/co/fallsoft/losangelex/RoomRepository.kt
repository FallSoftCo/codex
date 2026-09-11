package co.fallsoft.losangelex

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Response
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.security.MessageDigest

data class RoomEvent(val id: Long, val author: String, val task: String, val body: String,
                     val kind: String, val visibility: String, val canAccept: Boolean = false,
                     val open: Boolean = true, val resolves: Long? = null,
                     val createdAt: Long = 0, val replyTo: Long? = null,
                     val replyAuthor: String = "", val replyBody: String = "") {
    companion object {
        fun from(json: JSONObject) = RoomEvent(json.getLong("id"), json.getString("author"),
            json.getString("task"), json.getString("body"), json.getString("kind"),
            json.optString("visibility", "room"), json.optJSONObject("data")?.optBoolean("canAccept") ?: false,
            json.optBoolean("open", true), json.optJSONObject("data")?.optLong("attention")?.takeIf { it > 0 },
            json.optLong("created_at"), json.optJSONObject("data")?.optLong("replyTo")?.takeIf { it > 0 },
            json.optJSONObject("reply")?.optString("author").orEmpty(),
            json.optJSONObject("reply")?.optString("body").orEmpty())
    }
}

class RoomRepository(context: Context) {
    val credentials = Credentials(context)
    private val directory = context.filesDir
    private val cacheWrite = Mutex()
    private fun cache(url: String) = File(directory, "room-${MessageDigest.getInstance("SHA-256")
        .digest(url.toByteArray()).joinToString("") { "%02x".format(it) }}.json")
    private val client = OkHttpClient.Builder().callTimeout(30, TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build()

    suspend fun request(path: String, payload: JSONObject? = null, host: HostConnection = credentials.read(),
                        method: String = if (payload == null) "GET" else "POST"): JSONObject = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(host.url + "/hollywood/v2/" + path)
            .header("Authorization", "Bearer " + host.token)
            .method(method, payload?.toString()?.toRequestBody("application/json".toMediaType()))
        client.newCall(request.build()).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) error("Request failed (${response.code}): " + body.take(200))
            JSONObject(body)
        }
    }

    suspend fun messages(after: Long): List<RoomEvent> {
        val data = request("messages?after=$after").getJSONArray("data")
        return (0 until data.length()).map { RoomEvent.from(data.getJSONObject(it)) }
    }

    fun stream(after: Long) = callbackFlow {
        val host = credentials.read()
        val streaming = client.newBuilder().callTimeout(0, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()
        val call = streaming.newCall(Request.Builder().url(host.url + "/hollywood/v2/events?after=$after")
            .header("Authorization", "Bearer " + host.token).build())
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, error: IOException) { close(error) }
            override fun onResponse(call: Call, response: Response) {
                launch(Dispatchers.IO) {
                    try {
                        response.use {
                            check(it.isSuccessful) { "Stream rejected (${it.code})" }
                            val source = checkNotNull(it.body).source()
                            while (!source.exhausted()) {
                                val line = source.readUtf8Line() ?: break
                                if (line.startsWith("data: ")) send(RoomEvent.from(JSONObject(line.substring(6))))
                            }
                        }
                        close()
                    } catch (error: kotlinx.coroutines.CancellationException) { throw error }
                    catch (error: Exception) { close(error) }
                }
            }
        })
        awaitClose { call.cancel() }
    }

    suspend fun save(events: List<RoomEvent>, url: String = credentials.url) = withContext(Dispatchers.IO) { cacheWrite.withLock {
        val cache = cache(url)
        val array = JSONArray()
        events.takeLast(500).forEach { e -> array.put(JSONObject().put("id", e.id).put("author", e.author)
            .put("task", e.task).put("body", e.body).put("kind", e.kind).put("visibility", e.visibility)
            .put("open", e.open).put("created_at", e.createdAt)
            .put("data", JSONObject().put("canAccept", e.canAccept).put("replyTo", e.replyTo))
            .put("reply", JSONObject().put("author", e.replyAuthor).put("body", e.replyBody))) }
        val temporary = File(cache.parentFile, cache.name + ".tmp")
        temporary.writeText(array.toString())
        check(temporary.renameTo(cache))
    } }

    fun cached(): List<RoomEvent> = runCatching {
        val data = JSONArray(cache(credentials.url).readText())
        (0 until data.length()).map { RoomEvent.from(data.getJSONObject(it)) }
    }.getOrDefault(emptyList())
}
