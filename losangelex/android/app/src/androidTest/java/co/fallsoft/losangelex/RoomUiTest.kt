package co.fallsoft.losangelex

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.longClick
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import java.io.File
import java.util.UUID

class RoomUiTest {
    @get:Rule val compose = createComposeRule()

    @Test fun publicReplyKeepsSourceIdentityAndPrivateTextStaysSeparate() {
        val event = RoomEvent(1, "maya", "notifications", "Use a generic alert", "message", "room")
        val private = RoomEvent(2, "maya", "notifications", "Private diagnostic", "message", "direct:maya")
        var target: RoomEvent? = null
        compose.setContent { MaterialTheme {
            RoomScreen(RoomState(events = listOf(event, private)), "https://host.example", { _, _ -> }, {}, {},
                { e, _ -> target = e }, {})
        } }
        compose.onNodeWithText("Use a generic alert").assertIsDisplayed()
        compose.onNodeWithText("Private diagnostic").assertDoesNotExist()
        compose.onNodeWithText("Use a generic alert").performTouchInput { longClick() }
        compose.onNodeWithText("Reply").performClick()
        assertEquals(event, target)
    }

    @Test fun emulatorUsesAuthenticatedRoomApiAndRetainsCommandIdentity() = runBlocking {
        val args = InstrumentationRegistry.getArguments()
        val url = args.getString("roomServerUrl")
        assumeTrue("Run with an explicitly configured Hollywood test server", url != null)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val repository = RoomRepository(context)
        val tokenFile = args.getString("roomTokenFile")?.let { File(context.filesDir, it) }
        val token = tokenFile?.readText()?.trim() ?: "android-fixture"
        tokenFile?.delete()
        repository.credentials.connect(url!!, token)
        val payload = JSONObject().put("commandId", UUID.randomUUID().toString())
            .put("body", "Maya, this is a connection test. Reply only 'Android chat connected'. " +
                "Do not use tools, delegate, inspect files or make changes.")
        val first = repository.request("messages", payload)
        val retry = repository.request("messages", payload)
        assertEquals(first.getLong("id"), retry.getLong("id"))
        assertEquals("you", first.getString("author"))
        assertTrue(repository.messages(first.getLong("id") - 1).any { it.id == first.getLong("id") })
        val original = repository.credentials.read()
        repository.credentials.connect("https://different.invalid", "different-host-fixture")
        try {
            val captured = repository.request("messages", payload, host = original)
            assertEquals(first.getLong("id"), captured.getLong("id"))
        } finally {
            repository.credentials.connect(original.url, original.token)
        }
    }
}
