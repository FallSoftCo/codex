package co.fallsoft.losangelex

import android.app.Application
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class RoomDraftTest {
    @Test fun retryRetainsOriginalMessageWhileAnotherConversationKeepsItsDraftAndReply() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val url = InstrumentationRegistry.getArguments().getString("historyServerUrl")
        assumeTrue("Requires isolated history server", url != null)
        val application = instrumentation.targetContext.applicationContext as Application
        val preferences = application.getSharedPreferences("drafts", Application.MODE_PRIVATE)
        preferences.edit().clear().commit()
        val owner = ViewModelStore()
        lateinit var model: RoomViewModel
        instrumentation.runOnMainSync {
            model = ViewModelProvider(owner, ViewModelProvider.AndroidViewModelFactory(application))[RoomViewModel::class.java]
            model.connect(url!!, "invalid-fixture-token")
            model.focus(null, "maya")
            model.draft("Please review this interface.")
            model.send()
        }
        try {
            await { model.state.value.pending && !model.state.value.sending }
            assertNotNull(model.state.value.sendError)
            val original = JSONObject(preferences.getString("pending", null)!!)
            val reply = RoomEvent(653, "theo", "lobby", "Private source", "message", "direct:theo")
            val generation = model.state.value.historyGeneration
            instrumentation.runOnMainSync {
                model.focus(reply, "theo")
                model.draft("Keep this separate draft.")
                model.connect(url!!, "android-fixture")
                model.send()
            }
            await { !model.state.value.pending && !model.state.value.sending }
            assertEquals("Keep this separate draft.", model.state.value.draft)
            assertEquals(reply, model.state.value.reply)
            assertEquals(generation, model.state.value.historyGeneration)
            val receipt = model.repository.request("commands/${original.getString("commandId")}").getJSONObject("event")
            assertEquals(mapOf("body" to "Please review this interface.", "task" to "lobby", "visibility" to "direct:maya"),
                listOf("body", "task", "visibility").associateWith { receipt.getString(it) })
            instrumentation.runOnMainSync { model.focus(null, "maya") }
            assertEquals("", model.state.value.draft)
            instrumentation.runOnMainSync { model.focus(null, "theo") }
            assertEquals("Keep this separate draft.", model.state.value.draft)
        } finally { instrumentation.runOnMainSync { owner.clear() } }
    }

    private suspend fun await(condition: () -> Boolean) {
        repeat(250) { if (condition()) return; delay(20) }
        error("Timed out waiting for message state")
    }
}
