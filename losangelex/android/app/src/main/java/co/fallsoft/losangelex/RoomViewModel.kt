package co.fallsoft.losangelex

import android.app.Application
import android.app.NotificationManager
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.paging.Pager
import androidx.paging.PagingConfig
import androidx.paging.PagingData
import androidx.paging.cachedIn
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.UUID

data class RoomState(
    val hostUrl: String = "",
    val connected: Boolean = false, val status: String = "Connect to your Hollywood host",
    val pushStatus: String = "Background notifications are not configured",
    val events: List<RoomEvent> = emptyList(), val draft: String = "", val task: String = "lobby",
    val recipient: String = "room", val replyTo: Long? = null, val pending: Boolean = false,
    val controlPending: Boolean = false,
    val reply: RoomEvent? = null, val sending: Boolean = false, val sendError: String? = null,
    val historyAnchor: Long? = null, val historyGeneration: Int = 0, val liveRevision: Long = 0,
    val tasks: Map<String, String> = mapOf("lobby" to "All tasks"),
    val pendingBody: String = "", val pendingRecipient: String = "room",
)

class RoomViewModel(application: Application) : AndroidViewModel(application) {
    val repository = RoomRepository(application)
    private val preferences = application.getSharedPreferences("drafts", Application.MODE_PRIVATE)
    private val mutable = MutableStateFlow(RoomState(hostUrl = repository.credentials.url, events = repository.cached(),
        draft = preferences.getString(draftKey("lobby", "room"), "").orEmpty(),
        pending = preferences.contains("pending"), controlPending = preferences.contains("pendingControl"),
        pendingBody = preferences.getString("pending", null)?.let { JSONObject(it).optString("body") }.orEmpty(),
        pendingRecipient = preferences.getString("pendingScope", null)?.substringAfterLast(':') ?: "room"))
    val state = mutable.asStateFlow()
    private var historySource: RoomHistorySource? = null
    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    val history = mutable.map { HistorySelection(it.hostUrl, it.task, it.recipient,
        it.historyAnchor, it.historyGeneration) }.distinctUntilChanged().flatMapLatest { selection ->
        val host = repository.credentials.read()
        if (selection.host.isEmpty()) flowOf(PagingData.empty()) else Pager(
            config = PagingConfig(pageSize = 50, initialLoadSize = 50, prefetchDistance = 8,
                enablePlaceholders = false, maxSize = 250),
            initialKey = selection.anchor?.let { HistoryKey("around", it) },
            pagingSourceFactory = { RoomHistorySource(repository, host, selection, mutable.value.events) { recent ->
                if (repository.credentials.url == host.url) {
                    mutable.update { it.copy(events = (it.events.filter { e -> recent.none { r -> e.id == r.id } } + recent)
                        .sortedBy { e -> e.id }.takeLast(500)) }
                    repository.save(mutable.value.events, host.url)
                }
            }
                .also { historySource = it } },
        ).flow
    }.cachedIn(viewModelScope)
    private var foreground = false
    private var connection: Job? = null
    private var sending = false
    private var notificationToOpen: String? = null
    private fun draftKey(task: String, recipient: String) = "${repository.credentials.url}:$task:$recipient"

    fun draft(text: String) {
        mutable.update { it.copy(draft = text) }
        val value = mutable.value
        preferences.edit().putString(draftKey(value.task, value.recipient), text).apply()
    }

    fun focus(event: RoomEvent? = null, recipient: String = "room") {
        val task = event?.task ?: "lobby"
        mutable.update { it.copy(task = task, recipient = recipient, replyTo = event?.id, reply = event,
            historyAnchor = null,
            draft = preferences.getString(draftKey(task, recipient), "").orEmpty()) }
    }

    fun selectTask(task: String) {
        val recipient = mutable.value.recipient
        mutable.update { it.copy(task = task, replyTo = null, reply = null, historyAnchor = null,
            draft = preferences.getString(draftKey(task, recipient), "").orEmpty()) }
    }

    fun cancelReply() { mutable.update { it.copy(replyTo = null, reply = null) } }

    fun latest() { mutable.update { it.copy(historyAnchor = null, historyGeneration = it.historyGeneration + 1) } }

    fun connect(url: String, token: String) {
        require(url.startsWith("https://") || (BuildConfig.DEBUG &&
            (url.startsWith("http://10.0.2.2:") || url.startsWith("http://127.0.0.1:")))) {
            "Use an HTTPS URL for your private host"
        }
        require(token.isNotBlank()) { "Enter the host's device access token" }
        if (url.trimEnd('/') != repository.credentials.url && (mutable.value.pending || mutable.value.controlPending)) {
            error("Reconcile the pending submission before changing hosts")
        }
        val changed = repository.credentials.url != url.trimEnd('/')
        val previous = runCatching { repository.credentials.read() }.getOrNull()
        repository.credentials.connect(url, token)
        if (changed && previous != null && previous.url.isNotEmpty()) {
            val id = getApplication<Application>().getSharedPreferences("push", Application.MODE_PRIVATE)
                .getString("deviceId:${previous.url}", null)
            if (id != null) viewModelScope.launch {
                try { repository.request("devices/$id", host = previous, method = "DELETE") }
                catch (error: CancellationException) { throw error }
                catch (error: Exception) { /* Old-host alerts are also rejected by their registration ID. */ }
            }
        }
        mutable.update { if (changed) RoomState(hostUrl = repository.credentials.url, status = "Connecting…", events = repository.cached(),
            draft = preferences.getString(draftKey("lobby", "room"), "").orEmpty()) else it.copy(status = "Connecting…") }
        connection?.cancel()
        connection = null
        if (foreground) foreground(true)
    }

    fun foreground(active: Boolean) {
        foreground = active
        if (!active) { connection?.cancel(); connection = null; return }
        if (connection?.isActive == true) return
        connection = viewModelScope.launch {
            var backoff = 1000L
            var streamCursor: Long? = null
            while (foreground) {
                if (repository.credentials.url.isEmpty()) { delay(1000); continue }
                try {
                    val overview = repository.request("overview")
                    val tasks = overview.getJSONArray("tasks")
                    mutable.update { it.copy(connected = true, status = if (overview.optBoolean("runtimeReady"))
                        "Connected · shared team room" else "Connected · Codex runtime needs attention",
                        tasks = mapOf("lobby" to "All tasks") + (0 until tasks.length()).map { i ->
                            tasks.getJSONObject(i).let { task -> task.getString("id") to task.getString("title") }
                        }.filter { (id, _) -> id != "lobby" }.toMap()) }
                    if (streamCursor == null) streamCursor = overview.getLong("cursor")
                    historySource?.invalidate()
                    syncPush()
                    val pending = preferences.getString("pending", null)?.let(::JSONObject)
                    if (pending != null) {
                        try {
                            val receipt = repository.request("commands/${pending.getString("commandId")}")
                            receive(RoomEvent.from(receipt.getJSONObject("event")))
                            confirm(pending)
                        } catch (error: CancellationException) { throw error }
                        catch (error: Exception) { /* Keep the original command until confirmed. */ }
                    }
                    val attention = overview.getJSONArray("attention")
                    val open = (0 until attention.length()).map { attention.getJSONObject(it).getLong("id") }.toSet()
                    mutable.update { it.copy(events = it.events.map { e ->
                        if (e.kind in setOf("attention", "approval")) e.copy(open = e.id in open) else e
                    }) }
                    notificationToOpen?.let { openAttention(it) }
                    backoff = 1000
                    repository.stream(checkNotNull(streamCursor)).collect { event ->
                        receive(event)
                        streamCursor = event.id
                        repository.save(mutable.value.events)
                    }
                    backoff = 1000
                    delay(1000)
                } catch (error: CancellationException) { throw error }
                catch (error: Exception) {
                    mutable.update { it.copy(connected = false, status = "Disconnected · drafts retained · retrying") }
                    delay(backoff)
                    backoff = (backoff * 2).coerceAtMost(30000)
                }
            }
        }
    }

    private fun receive(event: RoomEvent) {
        val selected = mutable.value
        val visible = event.kind in chatKinds && (selected.task == "lobby" || selected.task == event.task) &&
            event.visibility == (if (selected.recipient == "room") "room" else "direct:${selected.recipient}")
        mutable.update { current -> current.copy(events = (current.events.filter { it.id != event.id } + event)
            .map { if (it.id == event.resolves) it.copy(open = false, canAccept = false) else it }
            .sortedBy { it.id }.takeLast(500),
            tasks = if (event.kind == "task") current.tasks + (event.task to event.body) else current.tasks,
            liveRevision = if (visible) event.id else current.liveRevision) }
        if (visible || event.resolves != null) historySource?.invalidate()
    }

    private suspend fun registerPush() {
        val push = getApplication<Application>().getSharedPreferences("push", Application.MODE_PRIVATE)
        val fid = push.getString("fid", null) ?: return
        val registrationKey = "deviceId:${repository.credentials.url}"
        val id = push.getString(registrationKey, null) ?: UUID.randomUUID().toString().also {
            push.edit().putString(registrationKey, it).apply()
        }
        val result = repository.request("devices", JSONObject().put("id", id).put("fid", fid))
        val permitted = getApplication<Application>().getSystemService(NotificationManager::class.java).areNotificationsEnabled()
        mutable.update { it.copy(pushStatus = when {
            !permitted -> "Notifications are disabled in Android settings"
            !result.optBoolean("pushConfigured") -> "Host notification provider is not configured"
            push.getString("lastDeviceId", null) == id -> "Notifications active · this device has received an alert"
            else -> "Notifications registered · delivery requires a device test"
        }) }
    }

    fun syncPush() = viewModelScope.launch {
        if (repository.credentials.url.isNotBlank()) {
            try { registerPush() }
            catch (error: CancellationException) { throw error }
            catch (error: Exception) { mutable.update { it.copy(pushStatus = "Notification registration pending; reconnect retries") } }
        }
    }

    fun openAttention(id: String) = viewModelScope.launch {
        if (id.toLongOrNull() == null) return@launch
        notificationToOpen = id
        try {
            val detail = repository.request("messages/$id")
            val event = RoomEvent.from(detail.getJSONObject("event")).copy(open = detail.optString("attentionState") == "open")
            mutable.update { it.copy(events = (it.events.filter { e -> e.id != event.id } + event).sortedBy { e -> e.id }.takeLast(500)) }
            focus(event, if (event.visibility == "room") "room" else event.author)
            mutable.update { it.copy(historyAnchor = event.id, historyGeneration = it.historyGeneration + 1) }
            if (!event.open) {
                mutable.update { it.copy(replyTo = null, reply = null, status = "This notification has already been handled") }
            }
            notificationToOpen = null
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) { mutable.update { it.copy(status = "Connect to the host to open this notification") } }
    }

    fun send() = viewModelScope.launch {
        if (sending) return@launch
        val current = mutable.value
        if (current.draft.isBlank() && !current.pending) return@launch
        val source = current.reply ?: current.events.find { it.id == current.replyTo }
        val path = preferences.getString("pendingPath", null)
            ?: if (source?.kind == "attention" && source.open) "attention/${source.id}/answer" else "messages"
        val payload = preferences.getString("pending", null)?.let(::JSONObject) ?: JSONObject()
            .put("commandId", UUID.randomUUID().toString()).put("body", current.draft)
            .apply {
                if (path == "messages") {
                    put("task", current.task).put("visibility", if (current.recipient == "room") "room" else "direct")
                    put("targets", org.json.JSONArray().apply { if (current.recipient != "room") put(current.recipient) })
                    current.replyTo?.let { put("replyTo", it) }
                }
            }
        // Preserve ID and scope before submitting; reconnect never invents a new action.
        val scope = preferences.getString("pendingScope", null) ?: draftKey(current.task, current.recipient)
        check(preferences.edit().putString("pending", payload.toString()).putString("pendingPath", path)
            .putString("pendingScope", scope).commit())
        sending = true
        mutable.update { it.copy(pending = true, sending = true, sendError = null,
            pendingBody = payload.getString("body"), pendingRecipient = scope.substringAfterLast(':')) }
        try {
            receive(RoomEvent.from(repository.request(path, payload)))
            confirm(payload)
            if (draftKey(mutable.value.task, mutable.value.recipient) == scope) latest()
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) {
            mutable.update { it.copy(sendError = "Message not confirmed. Retry sends the same message to its original conversation.") }
        } finally { sending = false; mutable.update { it.copy(sending = false) } }
    }

    private fun confirm(payload: JSONObject) {
        val current = mutable.value
        val scope = preferences.getString("pendingScope", null)
        val clearVisibleDraft = scope == draftKey(current.task, current.recipient) && current.draft == payload.getString("body")
        preferences.edit().apply {
            if (scope != null && preferences.getString(scope, null) == payload.getString("body")) remove(scope)
            remove("pending").remove("pendingPath").remove("pendingScope")
        }.commit()
        mutable.update { it.copy(pending = false, sendError = null, pendingBody = "",
            draft = if (clearVisibleDraft) "" else it.draft,
            replyTo = if (clearVisibleDraft) null else it.replyTo,
            reply = if (clearVisibleDraft) null else it.reply) }
    }

    fun answer(event: RoomEvent) = focus(event, if (event.visibility == "room") "room" else event.author)

    fun approve(event: RoomEvent, decision: String) = viewModelScope.launch {
        try {
            repository.request("approval/${event.id}/answer", JSONObject().put("decision", decision))
            mutable.update { it.copy(status = "Approval response submitted") }
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) { mutable.update { it.copy(status = "Approval unconfirmed or expired; refresh the current request") } }
    }

    fun stop() = viewModelScope.launch {
        val current = mutable.value
        val payload = preferences.getString("pendingControl", null)?.let(::JSONObject) ?: JSONObject()
            .put("commandId", UUID.randomUUID().toString()).put("task", current.task)
            .put("agent", current.recipient).put("action", "interrupt")
        check(preferences.edit().putString("pendingControl", payload.toString()).commit())
        mutable.update { it.copy(controlPending = true) }
        try {
            val response = repository.request("control", payload)
            preferences.edit().remove("pendingControl").commit()
            mutable.update { it.copy(controlPending = false, status = "Stop: ${response.getString("state")}") }
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) { mutable.update { it.copy(status = "Stop unconfirmed · retry retains the original target") } }
    }
}
