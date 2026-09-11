package co.fallsoft.losangelex

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.paging.LoadState
import androidx.paging.compose.LazyPagingItems
import androidx.paging.compose.itemKey
import kotlinx.coroutines.flow.distinctUntilChanged
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun ChatTimeline(state: RoomState, messages: LazyPagingItems<RoomEvent>, modifier: Modifier = Modifier,
                 focus: (RoomEvent?, String) -> Unit, answer: (RoomEvent) -> Unit,
                 approval: (RoomEvent, String) -> Unit, latest: () -> Unit) {
    val timeline = rememberLazyListState()
    var followNext by remember { mutableStateOf(true) }
    var atBottom by remember { mutableStateOf(true) }
    var positioned by remember { mutableStateOf(false) }
    LaunchedEffect(timeline) {
        snapshotFlow { timeline.firstVisibleItemIndex == 0 && timeline.firstVisibleItemScrollOffset < 80 }
            .distinctUntilChanged().collect { atBottom = it }
    }
    LaunchedEffect(state.liveRevision) { followNext = atBottom && state.historyAnchor == null }
    LaunchedEffect(messages.itemSnapshotList.items.firstOrNull()?.id, messages.loadState.refresh) {
        if (messages.loadState.refresh is LoadState.NotLoading && messages.itemCount > 0) {
            if (!positioned && state.historyAnchor != null) {
                val index = messages.itemSnapshotList.items.indexOfFirst { it.id == state.historyAnchor }
                if (index >= 0) timeline.scrollToItem(index)
            } else if (followNext && state.historyAnchor == null) timeline.scrollToItem(0)
            followNext = false
            positioned = true
        }
    }
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
        LazyColumn(Modifier.widthIn(max = 760.dp).fillMaxSize().testTag("chat-history"), state = timeline,
            reverseLayout = true, contentPadding = PaddingValues(horizontal = 12.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.Bottom)) {
            if (messages.loadState.prepend is LoadState.Loading) item("newer-loading") { HistoryLoading("Loading newer messages…") }
            if (messages.loadState.prepend is LoadState.Error) item("newer-error") { HistoryRetry { messages.retry() } }
            items(messages.itemCount, key = messages.itemKey { it.id }) { index ->
                messages[index]?.let { event ->
                    Column(Modifier.testTag("message-${event.id}")) {
                        val older = if (index + 1 < messages.itemCount) messages.peek(index + 1) else null
                        if (event.createdAt > 0 && (older == null || older.day() != event.day())) {
                            val day = event.day()
                            val label = when (day) {
                                LocalDate.now() -> "Today"
                                LocalDate.now().minusDays(1) -> "Yesterday"
                                else -> day.format(DateTimeFormatter.ofPattern("MMM d, yyyy"))
                            }
                            Box(Modifier.fillMaxWidth().padding(vertical = 12.dp), contentAlignment = Alignment.Center) {
                                Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        ChatMessage(event, state.tasks[event.task] ?: event.task,
                            reply = { focus(event, state.recipient) }, direct = { focus(event, event.author) },
                            answer = { answer(event) }, approval = { approval(event, it) }, connected = state.connected)
                    }
                }
            }
            item("older-state") {
                // Keep the boundary's height stable while Paging swaps generations, so an
                // arrival cannot move the first message under someone reading the beginning.
                Box(Modifier.fillMaxWidth().heightIn(min = 48.dp), contentAlignment = Alignment.Center) {
                    when {
                        messages.loadState.append is LoadState.Loading -> HistoryLoading("Loading earlier messages…")
                        messages.loadState.append is LoadState.Error -> HistoryRetry { messages.retry() }
                        messages.loadState.append.endOfPaginationReached && messages.itemCount > 0 ->
                            Text("Beginning of conversation", style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        if (messages.itemCount == 0) Column(Modifier.align(Alignment.Center).padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            when (messages.loadState.refresh) {
                is LoadState.Loading -> HistoryLoading("Opening conversation…")
                is LoadState.Error -> HistoryRetry { messages.retry() }
                else -> {
                    AgentAvatar(state.recipient, size = 64.dp)
                    Spacer(Modifier.height(16.dp))
                    Text(if (state.recipient == "room") "Your team, in one conversation" else "A conversation with ${identity(state.recipient).name}",
                        style = MaterialTheme.typography.titleMedium, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                    Text(if (state.recipient == "room") "Start with an idea. Mention a teammate whenever you need them." else identity(state.recipient).role,
                        Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                }
            }
        }
        if (!atBottom || state.historyAnchor != null) FilledTonalButton(latest, Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp)) {
            Icon(painterResource(R.drawable.ic_chat_down), null, Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp)); Text("Latest")
        }
    }
}

@Composable
private fun HistoryLoading(label: String) {
    Row(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
        Spacer(Modifier.width(8.dp)); Text(label, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
private fun HistoryRetry(retry: () -> Unit) {
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        Text("Couldn't load messages. Your place is saved.", style = MaterialTheme.typography.bodySmall)
        TextButton(retry) { Text("Try again") }
    }
}
