package co.fallsoft.losangelex

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.installations.FirebaseInstallations

class MainActivity : ComponentActivity() {
    private val model: RoomViewModel by viewModels()
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
        if (FirebaseApp.initializeApp(this) != null) {
            FirebaseMessaging.getInstance().register().continueWithTask { registration ->
                if (!registration.isSuccessful) throw checkNotNull(registration.exception)
                FirebaseInstallations.getInstance().id
            }.addOnSuccessListener { fid ->
                getSharedPreferences("push", MODE_PRIVATE).edit().putString("fid", fid).apply()
                model.syncPush()
            }
        }
        intent.getStringExtra("attentionId")?.let(model::openAttention)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFF70DFBB), background = Color(0xFF101820))) {
                val state by model.state.collectAsStateWithLifecycle()
                RoomScreen(state, model.repository.credentials.url, model::connect, model::draft,
                    { model.send() }, model::focus, { model.answer(it) }, { event, decision -> model.approve(event, decision) }, { model.stop() })
            }
        }
    }
    override fun onStart() { super.onStart(); model.foreground(true) }
    override fun onStop() { model.foreground(false); super.onStop() }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra("attentionId")?.let(model::openAttention)
    }
}

@Composable
fun RoomScreen(state: RoomState, initialUrl: String, connect: (String, String) -> Unit,
               draft: (String) -> Unit, send: () -> Unit,
               focus: (RoomEvent?, String) -> Unit, answer: (RoomEvent) -> Unit,
               approval: (RoomEvent, String) -> Unit = { _, _ -> }, stop: () -> Unit = {}) {
    var settings by remember { mutableStateOf(initialUrl.isEmpty()) }
    var url by remember { mutableStateOf(initialUrl) }
    var token by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }
    Surface(Modifier.fillMaxSize()) {
        Column(Modifier.safeDrawingPadding().imePadding().padding(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Losangelex", style = MaterialTheme.typography.headlineSmall)
                TextButton(onClick = { settings = true }) { Text("Connect") }
            }
            Text(state.status, style = MaterialTheme.typography.labelMedium)
            Text(state.pushStatus, style = MaterialTheme.typography.labelSmall)
            FlowRow {
                TextButton(onClick = { focus(null, "room") }) { Text("Team room") }
                Text("${state.task} · ${if (state.recipient == "room") "public" else "direct: ${state.recipient}"}",
                    Modifier.padding(top = 14.dp), style = MaterialTheme.typography.labelMedium)
                if (state.recipient != "room" || state.controlPending) {
                    TextButton(onClick = stop) { Text(if (state.controlPending) "Retry original stop" else "Stop agent") }
                }
            }
            val visibility = if (state.recipient == "room") "room" else "direct:${state.recipient}"
            val visible = state.events.filter { it.visibility == visibility && (state.task == "lobby" || it.task == state.task)
                && it.kind in setOf("message", "attention", "approval", "task", "control", "resolved") }
            val timeline = rememberLazyListState()
            var previousCount by remember(state.task, state.recipient) { mutableIntStateOf(0) }
            LaunchedEffect(state.task, state.recipient, visible.lastOrNull()?.id) {
                val lastVisible = timeline.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
                val wasAtEnd = previousCount == 0 || lastVisible >= previousCount - 2
                if (state.replyTo == null && wasAtEnd && visible.isNotEmpty()) {
                    timeline.animateScrollToItem(visible.lastIndex)
                }
                previousCount = visible.size
            }
            LaunchedEffect(state.replyTo) {
                val index = visible.indexOfFirst { it.id == state.replyTo }
                if (index >= 0) timeline.animateScrollToItem(index)
            }
            LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = timeline, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(visible, key = { it.id }) { event ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text("${event.author.replaceFirstChar { it.uppercase() }} · ${event.task}", fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.primary)
                            Text(event.body)
                            FlowRow {
                                TextButton(onClick = { focus(event, state.recipient) }) { Text("Reply") }
                                if (event.author in setOf("coordinator", "maya", "theo", "rowan")) {
                                    TextButton(onClick = { focus(event, event.author) }) { Text("Direct") }
                                }
                                if (event.kind == "attention") {
                                    TextButton(onClick = { answer(event) }, enabled = event.open && state.connected) { Text("Answer") }
                                }
                                if (event.kind == "approval") {
                                    TextButton(onClick = { approval(event, "accept") }, enabled = event.canAccept && event.open && state.connected) { Text("Approve once") }
                                    TextButton(onClick = { approval(event, "decline") }, enabled = event.open && state.connected) { Text("Decline") }
                                }
                            }
                        }
                    }
                }
            }
            state.replyTo?.let { Text("Replying to #$it", style = MaterialTheme.typography.labelSmall) }
            OutlinedTextField(state.draft, draft, Modifier.fillMaxWidth(), maxLines = 5,
                label = { Text("Talk to your team · Maya, …") })
            Button(send, Modifier.fillMaxWidth()) { Text(if (state.pending) "Retry original submission" else "Send") }
        }
    }
    if (settings) AlertDialog(onDismissRequest = { settings = false }, title = { Text("Connect to Hollywood") },
        text = { Column {
            OutlinedTextField(url, { url = it }, label = { Text("Private HTTPS host") })
            OutlinedTextField(token, { token = it }, label = { Text("Device access token") }, visualTransformation = PasswordVisualTransformation())
            if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
        } }, confirmButton = { TextButton(onClick = {
            runCatching { connect(url, token) }.onSuccess { settings = false; token = "" }.onFailure { error = it.message.orEmpty() }
        }) { Text("Connect") } })
}
