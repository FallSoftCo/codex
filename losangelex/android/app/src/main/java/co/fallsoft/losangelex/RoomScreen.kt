package co.fallsoft.losangelex

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.paging.PagingData
import androidx.paging.LoadState
import androidx.paging.LoadStates
import androidx.paging.compose.collectAsLazyPagingItems
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf

@Composable
fun RoomScreen(state: RoomState, initialUrl: String, connect: (String, String) -> Unit,
               draft: (String) -> Unit, send: () -> Unit,
               focus: (RoomEvent?, String) -> Unit, answer: (RoomEvent) -> Unit,
               approval: (RoomEvent, String) -> Unit = { _, _ -> }, stop: () -> Unit = {},
               history: Flow<PagingData<RoomEvent>>? = null, cancelReply: () -> Unit = {},
               selectTask: (String) -> Unit = {}, latest: () -> Unit = {}) {
    var settings by remember { mutableStateOf(initialUrl.isEmpty()) }
    var menu by remember { mutableStateOf(false) }
    var tasks by remember { mutableStateOf(false) }
    var people by remember { mutableStateOf(false) }
    BackHandler(state.replyTo != null || state.recipient != "room" || state.task != "lobby") {
        if (state.replyTo != null) cancelReply() else focus(null, "room")
    }
    val local = remember(state.events, state.task, state.recipient) {
        flowOf(PagingData.from(state.events.filter {
            it.visibility == (if (state.recipient == "room") "room" else "direct:${state.recipient}") &&
                (state.task == "lobby" || it.task == state.task) && it.kind in chatKinds
        }.sortedByDescending { it.id }, sourceLoadStates = LoadStates(
            refresh = LoadState.NotLoading(false), prepend = LoadState.NotLoading(true), append = LoadState.NotLoading(true))))
    }
    val messages = (history ?: local).collectAsLazyPagingItems()
    Surface(Modifier.fillMaxSize()) {
        Column(Modifier.safeDrawingPadding().imePadding(), horizontalAlignment = Alignment.CenterHorizontally) {
            Row(Modifier.widthIn(max = 760.dp).fillMaxWidth().padding(start = 16.dp, top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                if (state.recipient == "room") Image(painterResource(R.drawable.hollywood_hills), null, Modifier.size(46.dp))
                else AgentAvatar(state.recipient, size = 44.dp)
                Column(Modifier.weight(1f).padding(start = 12.dp).clickable(onClickLabel = "Choose conversation") { people = true }) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(identity(state.recipient).name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                        Icon(painterResource(R.drawable.ic_chat_chevron), null, Modifier.padding(start = 6.dp).size(14.dp))
                    }
                    Text(if (!state.connected) if (initialUrl.isEmpty()) "Connect to your team" else "Reconnecting · drafts saved"
                        else if (state.recipient == "room") "Losangelex · Shared conversation" else "Private · ${identity(state.recipient).role}",
                        style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    DropdownMenu(people, { people = false }) {
                        (listOf("room") + teammates).forEach { agent ->
                            DropdownMenuItem(text = { Text(identity(agent).name) },
                                leadingIcon = { AgentAvatar(agent, size = 28.dp) },
                                onClick = { people = false; focus(null, agent) })
                        }
                    }
                }
                Box {
                    IconButton({ menu = true }) { Icon(painterResource(R.drawable.ic_chat_more), "Conversation options") }
                    DropdownMenu(menu, { menu = false }) {
                        DropdownMenuItem(text = { Text("Connection & notifications") }, onClick = { menu = false; settings = true })
                        if (state.recipient != "room" || state.controlPending) DropdownMenuItem(
                            text = { Text(if (state.controlPending) "Retry original stop" else "Stop ${identity(state.recipient).name}") },
                            onClick = { menu = false; stop() })
                    }
                }
            }
            AnimatedVisibility(WindowInsets.ime.getBottom(LocalDensity.current) == 0) {
              LazyRow(Modifier.widthIn(max = 760.dp).fillMaxWidth(), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(listOf("room") + teammates) { agent ->
                    val selected = agent == state.recipient
                    Surface(onClick = { focus(null, agent) }, shape = RoundedCornerShape(16.dp),
                        color = if (selected) MaterialTheme.colorScheme.surfaceContainerHigh else MaterialTheme.colorScheme.surface,
                        modifier = Modifier.width(68.dp).semantics {
                            contentDescription = "Open ${identity(agent).name} conversation"
                            this.selected = selected
                        }) {
                        Column(Modifier.padding(vertical = 7.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            AgentAvatar(agent, size = 32.dp)
                            Text(if (agent == "room") "Team" else identity(agent).name, maxLines = 1,
                                overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.labelSmall,
                                color = if (selected) identity(agent).color else MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(top = 4.dp))
                        }
                    }
                }
              }
            }
            Row(Modifier.widthIn(max = 760.dp).fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) {
                    TextButton({ tasks = true }) {
                        Text(state.tasks[state.task] ?: state.task, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Icon(painterResource(R.drawable.ic_chat_chevron), "Choose task", Modifier.size(16.dp).padding(start = 4.dp))
                    }
                    DropdownMenu(tasks, { tasks = false }) {
                        state.tasks.forEach { (id, title) -> DropdownMenuItem(text = { Text(title) },
                            onClick = { tasks = false; selectTask(id) }) }
                    }
                }
                if (!state.connected && initialUrl.isEmpty()) TextButton({ settings = true }) { Text("Connect") }
                else Text(when {
                    !state.connected -> "Offline"
                    state.status == "Connected · shared team room" || state.status == "Connect to your Hollywood host" -> "Connected"
                    else -> state.status.removePrefix("Connected · ")
                }, style = MaterialTheme.typography.labelSmall, maxLines = 2, overflow = TextOverflow.Ellipsis,
                    color = if (state.connected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.widthIn(max = 200.dp).padding(end = 8.dp))
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            key(state.task, state.recipient, state.historyGeneration) {
                ChatTimeline(state, messages, Modifier.weight(1f), focus, answer, approval, latest)
            }
            ChatComposer(state, draft, send, cancelReply)
        }
    }
    if (settings) ConnectionDialog(initialUrl, state, connect) { settings = false }
}

@Composable
private fun ConnectionDialog(initialUrl: String, state: RoomState, connect: (String, String) -> Unit, dismiss: () -> Unit) {
    var url by remember { mutableStateOf(initialUrl) }
    var token by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = dismiss, title = { Text("Connection & notifications") },
        text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(state.status, style = MaterialTheme.typography.bodyMedium)
            Text(state.pushStatus, style = MaterialTheme.typography.bodySmall)
            OutlinedTextField(url, { url = it }, label = { Text("Private HTTPS host") }, singleLine = true)
            OutlinedTextField(token, { token = it }, label = { Text("Device access token") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false))
            if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
        } }, confirmButton = { TextButton(onClick = {
            runCatching { connect(url, token) }.onSuccess { token = ""; dismiss() }.onFailure { error = it.message.orEmpty() }
        }) { Text("Connect") } }, dismissButton = { TextButton(dismiss) { Text("Done") } })
}
