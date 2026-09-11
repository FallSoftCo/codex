package co.fallsoft.losangelex

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.SoftwareKeyboardController
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.paging.PagingData
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import java.io.File
import kotlin.math.abs

class ChatUiTest {
    @get:Rule val compose = createComposeRule()
    private val fixtures = listOf(
        RoomEvent(1, "coordinator", "lobby", "One room for the whole team. What shall we work on?", "message", "room", createdAt = 1788260400),
        RoomEvent(2, "you", "lobby", "Let’s make messaging feel effortless.", "message", "room", createdAt = 1788260460),
        RoomEvent(3, "maya", "lobby", "I’ll refine the conversation view and keep every teammate easy to recognize.", "message", "room", createdAt = 1788260520),
        RoomEvent(4, "theo", "lobby", "I’ll make older messages load as you scroll, while keeping your place.", "message", "room", createdAt = 1788260580),
    )

    @Test fun composerMentionsRepliesAndSendStates() {
        var state by mutableStateOf(RoomState(connected = true, events = fixtures))
        var sent = ""
        var keyboard: SoftwareKeyboardController? = null
        compose.setContent { MaterialTheme(colorScheme = RoomColors) {
            keyboard = LocalSoftwareKeyboardController.current
            RoomScreen(state, "https://fixture.example", { _, _ -> }, { state = state.copy(draft = it) },
                { sent = state.draft }, { event, recipient -> state = state.copy(reply = event, replyTo = event?.id, recipient = recipient) }, {},
                cancelReply = { state = state.copy(reply = null, replyTo = null) })
        } }
        compose.onNodeWithContentDescription("Send message").assertIsNotEnabled()
        compose.onNodeWithText("@").performClick()
        compose.onNodeWithTag("mention-maya").performClick()
        compose.onNodeWithTag("message-composer").performTextInput("Please review this.")
        compose.onNodeWithContentDescription("Send message").performClick()
        assertEquals("@maya Please review this.", sent)
        compose.runOnIdle { keyboard?.hide() }
        compose.waitUntil(5000) { compose.onAllNodesWithContentDescription("Open Team room conversation").fetchSemanticsNodes().isNotEmpty() }
        compose.waitForIdle()
        compose.onNodeWithText(fixtures.last().body).performTouchInput { longClick() }
        compose.onNodeWithText("Reply").performClick()
        compose.onNodeWithText("Replying to Theo").assertIsDisplayed()
        compose.onNodeWithContentDescription("Cancel reply").performClick()
        compose.onNodeWithText("Replying to Theo").assertDoesNotExist()
        compose.runOnIdle { state = state.copy(pending = true, sendError = "Message not confirmed.") }
        compose.onNodeWithContentDescription("Send message").assertIsNotEnabled()
        compose.onNodeWithText("Retry original message").assertIsDisplayed()
    }

    @Test fun newMessagesPreserveAnOlderReadingPositionAndLatestReturnsToTheEnd() {
        val old = (80L downTo 1L).map { RoomEvent(it, "maya", "lobby", "Message $it", "message", "room") }
        val history = MutableStateFlow(PagingData.from(old))
        var state by mutableStateOf(RoomState(connected = true))
        compose.setContent { MaterialTheme(colorScheme = RoomColors) {
            RoomScreen(state, "https://fixture.example", { _, _ -> }, {}, {}, { _, _ -> }, {},
                history = history, latest = { state = state.copy(historyGeneration = state.historyGeneration + 1) })
        } }
        compose.onNodeWithTag("chat-history").performScrollToIndex(30)
        val before = compose.onNodeWithTag("message-50").fetchSemanticsNode().boundsInRoot
        compose.runOnIdle {
            state = state.copy(liveRevision = 81)
            history.value = PagingData.from(listOf(old.first().copy(id = 81, body = "New arrival")) + old)
        }
        compose.waitForIdle()
        val after = compose.onNodeWithTag("message-50").fetchSemanticsNode().boundsInRoot
        assertTrue("Reading anchor moved: $before -> $after", abs(before.top - after.top) < 2f)
        compose.onNodeWithText("Latest").performClick()
        compose.onNodeWithText("New arrival").assertIsDisplayed()
    }

    @Test fun roomAndDirectReplySnapshots() {
        var state by mutableStateOf(RoomState(connected = true, events = fixtures))
        compose.setContent { MaterialTheme(colorScheme = RoomColors) {
            RoomScreen(state, "https://fixture.example", { _, _ -> }, {}, {}, { _, _ -> }, {})
        } }
        compose.onNodeWithText(fixtures.last().body).assertIsDisplayed()
        screenshot("team-room")
        compose.runOnIdle {
            val event = fixtures.last().copy(visibility = "direct:theo")
            state = state.copy(recipient = "theo", events = listOf(event), reply = event, replyTo = event.id,
                draft = "Keep the current message in view when an older page loads.")
        }
        compose.onNodeWithText("Replying to Theo").assertIsDisplayed()
        screenshot("direct-reply")
    }

    private fun screenshot(name: String) {
        compose.waitForIdle()
        val bitmap = compose.onRoot().captureToImage().asAndroidBitmap()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val output = File(instrumentation.targetContext.filesDir, "$name.png")
        output.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        if (InstrumentationRegistry.getArguments().getString("recordScreenshots") == "true") return
        val expected = instrumentation.context.assets.open("screenshots/$name.png").use(BitmapFactory::decodeStream)
        assertEquals("Snapshot width", expected.width, bitmap.width)
        assertEquals("Snapshot height", expected.height, bitmap.height)
        val actualPixels = IntArray(bitmap.width * bitmap.height)
        val expectedPixels = IntArray(actualPixels.size)
        bitmap.getPixels(actualPixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
        expected.getPixels(expectedPixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
        val changed = actualPixels.indices.count { actualPixels[it] != expectedPixels[it] }
        assertTrue("Snapshot changed: $changed pixels; inspect the recorded image before accepting", changed < actualPixels.size / 1000)
    }
}
