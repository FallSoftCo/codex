package co.fallsoft.losangelex

import android.app.NotificationManager
import android.content.Intent
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.test.platform.app.InstrumentationRegistry
import androidx.lifecycle.Lifecycle
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test

class NotificationUiTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    @Test fun receivedNotificationOpensItsPrivateConversationInAnExistingActivity() {
        val id = InstrumentationRegistry.getArguments().getString("notificationId")
        assumeTrue("Supply an actual Firebase-delivered private question", id != null)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val notification = context.getSystemService(NotificationManager::class.java)
            .activeNotifications.single { it.tag == id }
        val activity = compose.activity
        val originalIntent = Intent(activity.intent)
        try {
            notification.notification.contentIntent.send()
            compose.waitUntil(15000) {
                compose.onAllNodesWithText("lobby · direct: theo").fetchSemanticsNodes().isNotEmpty()
            }
            compose.onNodeWithText("Replying to #$id").assertIsDisplayed()
            assertTrue(activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
        } finally {
            // ActivityScenario matches lifecycle callbacks by its launch intent. The app's
            // onNewIntent correctly replaces that intent; restore test bookkeeping for cleanup.
            compose.runOnUiThread { activity.intent = originalIntent }
        }
    }
}
