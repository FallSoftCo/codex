package co.fallsoft.losangelex

import android.content.ClipData
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

fun RoomEvent.day() = Instant.ofEpochSecond(createdAt).atZone(ZoneId.systemDefault()).toLocalDate()

@Composable
fun ChatMessage(event: RoomEvent, taskTitle: String, reply: () -> Unit, direct: () -> Unit,
                answer: () -> Unit, approval: (String) -> Unit, connected: Boolean) {
    if (event.kind in setOf("task", "control", "resolved")) {
        Text(event.body, Modifier.fillMaxWidth().padding(vertical = 6.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelMedium,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        return
    }
    val own = event.author == "you"
    val person = identity(event.author)
    var menu by remember { mutableStateOf(false) }
    val clipboard = LocalClipboard.current
    val haptic = LocalHapticFeedback.current
    val scope = rememberCoroutineScope()
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (own) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top) {
        if (!own) {
            Box(Modifier.size(48.dp).combinedClickable(onClick = direct,
                onLongClick = { menu = true }, onClickLabel = "Message ${person.name} privately"), contentAlignment = Alignment.Center) {
                AgentAvatar(event.author, size = 38.dp)
            }
            Spacer(Modifier.width(8.dp))
        }
        Column(Modifier.widthIn(max = 620.dp).fillMaxWidth(if (own) .86f else .91f),
            horizontalAlignment = if (own) Alignment.End else Alignment.Start) {
            if (!own) Row(Modifier.padding(start = 4.dp, bottom = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(person.name, color = person.color, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
                Text(person.role, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelSmall,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Surface(color = if (own) androidx.compose.ui.graphics.Color(0xFF244D43) else MaterialTheme.colorScheme.surfaceContainer,
                shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp,
                    bottomStart = if (own) 18.dp else 4.dp, bottomEnd = if (own) 4.dp else 18.dp),
                modifier = Modifier.combinedClickable(onClick = {}, onLongClick = {
                    haptic.performHapticFeedback(HapticFeedbackType.LongPress); menu = true
                }, onLongClickLabel = "Message actions")) {
                Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    if (event.task != "lobby") Text(taskTitle, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    if (event.replyTo != null && event.replyBody.isNotBlank()) {
                        Surface(color = MaterialTheme.colorScheme.background.copy(alpha = .35f), shape = RoundedCornerShape(8.dp)) {
                            Column(Modifier.fillMaxWidth().padding(9.dp)) {
                                Text(identity(event.replyAuthor).name, color = identity(event.replyAuthor).color,
                                    style = MaterialTheme.typography.labelMedium)
                                Text(event.replyBody, maxLines = 2, overflow = TextOverflow.Ellipsis,
                                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                    }
                    if (event.kind in setOf("attention", "approval")) {
                        Text(if (event.open) if (event.kind == "approval") "APPROVAL REQUEST" else "NEEDS YOUR ANSWER" else "HANDLED",
                            style = MaterialTheme.typography.labelSmall, color = person.color,
                            modifier = Modifier.padding(bottom = 6.dp))
                    }
                    Text(event.body, style = MaterialTheme.typography.bodyLarge)
                    if (event.open && event.kind == "attention") TextButton(answer, enabled = connected) { Text("Answer") }
                    if (event.open && event.kind == "approval") FlowRow {
                        TextButton({ approval("accept") }, enabled = connected && event.canAccept) { Text("Approve once") }
                        TextButton({ approval("decline") }, enabled = connected) { Text("Decline") }
                    }
                    if (event.createdAt > 0) Text(
                        Instant.ofEpochSecond(event.createdAt).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("HH:mm")),
                        Modifier.align(Alignment.End).padding(top = 5.dp), style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            DropdownMenu(menu, { menu = false }) {
                DropdownMenuItem(text = { Text("Reply") }, onClick = { menu = false; reply() })
                DropdownMenuItem(text = { Text("Copy message") }, onClick = {
                    scope.launch { clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Message", event.body))) }; menu = false
                })
                if (event.author in teammates) DropdownMenuItem(text = { Text("Message ${person.name} privately") },
                    onClick = { menu = false; direct() })
            }
        }
    }
}
