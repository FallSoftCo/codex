package co.fallsoft.losangelex

import android.app.Application
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.paging.LoadState
import androidx.paging.compose.LazyPagingItems
import androidx.paging.compose.collectAsLazyPagingItems
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import java.util.UUID
import kotlin.math.abs

class ChatPagingTest {
    @get:Rule val compose = createComposeRule()
    private lateinit var paged: LazyPagingItems<RoomEvent>

    @Test fun scrollEntireRemoteHistoryThenReceiveLiveMessageWithoutLosingPlace() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val url = InstrumentationRegistry.getArguments().getString("historyServerUrl")
        assumeTrue("Requires the isolated 650-message fixture", url != null)
        val owner = ViewModelStore()
        lateinit var model: RoomViewModel
        instrumentation.runOnMainSync {
            model = ViewModelProvider(owner, ViewModelProvider.AndroidViewModelFactory(
                instrumentation.targetContext.applicationContext as Application))[RoomViewModel::class.java]
            model.connect(url!!, "android-fixture")
            model.foreground(true)
        }
        try {
            compose.setContent { MaterialTheme(colorScheme = RoomColors) {
                val state by model.state.collectAsState()
                val messages = model.history.collectAsLazyPagingItems()
                SideEffect { paged = messages }
                key(state.historyGeneration) {
                    ChatTimeline(state, messages, Modifier.fillMaxSize(), model::focus, { model.answer(it) },
                        { e, d -> model.approve(e, d) }, model::latest)
                }
            } }
            compose.waitUntil(15000) { ::paged.isInitialized && paged.itemCount >= 50 }
            var pages = 0
            while (paged.itemSnapshotList.items.last().id != 1L && pages < 30) {
                val oldest = paged.itemSnapshotList.items.last().id
                compose.onNodeWithTag("chat-history").performScrollToIndex(paged.itemCount - 4)
                compose.waitUntil(15000) { paged.itemSnapshotList.items.lastOrNull()?.id?.let { it < oldest } == true }
                pages++
            }
            assertTrue("Did not progressively load history", pages >= 10)
            assertEquals(1L, paged.itemSnapshotList.items.last().id)
            assertTrue("Loaded pages should be bounded", paged.itemCount <= 300)
            compose.onNodeWithTag("chat-history").performScrollToIndex(paged.itemCount - 1)
            val before = compose.onNodeWithTag("message-1").fetchSemanticsNode().boundsInRoot
            val marker = "Live arrival " + UUID.randomUUID().toString()
            val event = runBlocking { model.repository.request("messages", JSONObject()
                .put("commandId", UUID.randomUUID().toString()).put("body", marker)) }
            compose.waitUntil(15000) { model.state.value.liveRevision >= event.getLong("id") && paged.loadState.refresh is LoadState.NotLoading }
            compose.waitForIdle()
            val after = compose.onNodeWithTag("message-1").fetchSemanticsNode().boundsInRoot
            assertTrue("Live arrival moved the reading position: $before -> $after", abs(before.top - after.top) < 2f)
            compose.onNodeWithText("Latest").performClick()
            compose.waitUntil(15000) { compose.onAllNodesWithText(marker).fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText(marker).assertIsDisplayed()
        } finally { instrumentation.runOnMainSync { owner.clear() } }
    }
}
