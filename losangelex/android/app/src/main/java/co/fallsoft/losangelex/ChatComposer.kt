package co.fallsoft.losangelex

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.input.key.*
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp

@Composable
fun ChatComposer(state: RoomState, draft: (String) -> Unit, send: () -> Unit, cancelReply: () -> Unit) {
    val fieldFocus = remember { FocusRequester() }
    var field by remember(state.task, state.recipient) { mutableStateOf(TextFieldValue(state.draft, TextRange(state.draft.length))) }
    LaunchedEffect(state.draft) {
        if (state.draft != field.text) field = TextFieldValue(state.draft, TextRange(state.draft.length))
    }
    val tooLong = state.draft.length > 3500 || state.draft.toByteArray(Charsets.UTF_8).size > 6000
    val canSend = state.draft.isNotBlank() && state.connected && !state.pending && !tooLong
    var mentions by remember { mutableStateOf(false) }
    val mentionPrefix = Regex("^@([A-Za-z-]*)$").matchEntire(state.draft)?.groupValues?.get(1)
    LaunchedEffect(state.replyTo) { if (state.replyTo != null) fieldFocus.requestFocus() }
    Column(Modifier.widthIn(max = 760.dp).fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
        if (state.pending && !state.sending) Surface(color = MaterialTheme.colorScheme.surfaceContainerHigh, shape = RoundedCornerShape(12.dp)) {
            Column(Modifier.padding(12.dp)) {
                Text("To ${identity(state.pendingRecipient).name}", style = MaterialTheme.typography.labelMedium)
                if (state.pendingBody.isNotBlank()) Text(state.pendingBody, maxLines = 2,
                    overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                Text(state.sendError ?: "A previous message is awaiting confirmation.", style = MaterialTheme.typography.bodySmall)
                TextButton(send) { Text("Retry original message") }
            }
        }
        state.reply?.let { source ->
            Surface(color = MaterialTheme.colorScheme.surfaceContainerHigh, shape = RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp)) {
                Row(Modifier.fillMaxWidth().padding(start = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f).padding(vertical = 9.dp)) {
                        Text("Replying to ${identity(source.author).name}", color = identity(source.author).color,
                            style = MaterialTheme.typography.labelMedium)
                        Text(source.body, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                    }
                    IconButton(cancelReply) { Icon(painterResource(R.drawable.ic_chat_close), "Cancel reply") }
                }
            }
        }
        if (state.recipient == "room" && (mentions || mentionPrefix != null)) LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(teammates.filter { mentions || it.startsWith(mentionPrefix.orEmpty(), ignoreCase = true) }) { agent ->
                SuggestionChip(onClick = {
                    cancelReply()
                    draft("@$agent " + state.draft.replaceFirst(Regex("^@[\\w-]*\\s*"), ""))
                    mentions = false; fieldFocus.requestFocus()
                }, label = { Text(identity(agent).name) }, icon = { AgentAvatar(agent, size = 24.dp) }, modifier = Modifier.testTag("mention-$agent"))
            }
        }
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Surface(Modifier.weight(1f), color = MaterialTheme.colorScheme.surfaceContainerHigh, shape = RoundedCornerShape(26.dp)) {
                Row(verticalAlignment = Alignment.Bottom) {
                    if (state.recipient == "room") TextButton({ mentions = !mentions }, Modifier.size(48.dp), contentPadding = PaddingValues(0.dp)) {
                        Text("@", style = MaterialTheme.typography.titleLarge)
                    }
                    TextField(field, { field = it; draft(it.text) },
                        modifier = Modifier.weight(1f).testTag("message-composer").focusRequester(fieldFocus).onPreviewKeyEvent {
                            if (it.type == KeyEventType.KeyDown && it.key == Key.Enter && (it.isCtrlPressed || it.isMetaPressed) && canSend) {
                                send(); true
                            } else false
                        },
                        placeholder = { Text(if (state.recipient == "room") "Message the room…" else "Message ${identity(state.recipient).name}…") },
                        maxLines = 6, keyboardOptions = KeyboardOptions(autoCorrectEnabled = true),
                        colors = TextFieldDefaults.colors(focusedContainerColor = androidx.compose.ui.graphics.Color.Transparent,
                            unfocusedContainerColor = androidx.compose.ui.graphics.Color.Transparent,
                            focusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent,
                            unfocusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent))
                }
            }
            FilledIconButton(onClick = { send(); fieldFocus.requestFocus() }, enabled = canSend,
                modifier = Modifier.size(52.dp)) {
                if (state.sending) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                else Icon(painterResource(R.drawable.ic_chat_send), "Send message")
            }
        }
        if (tooLong) Text("Keep this message under 3,500 characters and 6 KB.", color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.labelSmall, modifier = Modifier.padding(top = 4.dp))
    }
}
