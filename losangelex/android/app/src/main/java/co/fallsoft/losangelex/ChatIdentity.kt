package co.fallsoft.losangelex

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

val RoomColors = darkColorScheme(
    primary = Color(0xFF70DFBB), onPrimary = Color(0xFF08251D),
    background = Color(0xFF101820), surface = Color(0xFF101820),
    surfaceContainer = Color(0xFF1B2832), surfaceContainerHigh = Color(0xFF243440),
    onSurface = Color(0xFFE8F0F4), onSurfaceVariant = Color(0xFFA5B7C3),
    outline = Color(0xFF526671), outlineVariant = Color(0xFF2B3E4A),
)

data class ChatIdentity(val name: String, val initials: String, val role: String, val color: Color)
val teammates = listOf("coordinator", "maya", "theo", "rowan")
fun identity(id: String): ChatIdentity = when (id) {
    "room" -> ChatIdentity("Team room", "LA", "Shared conversation", Color(0xFF70DFBB))
    "coordinator" -> ChatIdentity("Coordinator", "C", "Planning & coordination", Color(0xFFEAC17F))
    "maya" -> ChatIdentity("Maya", "M", "Interfaces & usability", Color(0xFFC4AEFF))
    "theo" -> ChatIdentity("Theo", "T", "Backend & systems", Color(0xFF82C9FF))
    "rowan" -> ChatIdentity("Rowan", "R", "Review & testing", Color(0xFFFFA6A6))
    "you" -> ChatIdentity("You", "Y", "", Color(0xFF70DFBB))
    else -> ChatIdentity(id.replaceFirstChar { it.uppercase() }, id.take(1).uppercase(), "", Color(0xFFA5B7C3))
}

@Composable
fun AgentAvatar(id: String, modifier: Modifier = Modifier, size: Dp = 36.dp) {
    val person = identity(id)
    Box(modifier.size(size).background(person.color.copy(alpha = .16f), CircleShape), contentAlignment = Alignment.Center) {
        Text(person.initials, color = person.color, fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.labelLarge)
    }
}
