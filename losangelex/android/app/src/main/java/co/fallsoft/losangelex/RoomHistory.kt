package co.fallsoft.losangelex

import androidx.paging.PagingSource
import androidx.paging.PagingState
import kotlinx.coroutines.CancellationException
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.io.IOException

val chatKinds = setOf("message", "attention", "approval", "task", "control", "resolved")

data class HistoryKey(val direction: String, val id: Long)
data class HistorySelection(val host: String, val task: String, val recipient: String,
                            val anchor: Long?, val generation: Int)

class RoomHistorySource(
    private val repository: RoomRepository,
    private val host: HostConnection,
    private val selection: HistorySelection,
    private val cached: List<RoomEvent> = emptyList(),
    private val onRecentPage: suspend (List<RoomEvent>) -> Unit = {},
) : PagingSource<HistoryKey, RoomEvent>() {
    override suspend fun load(params: LoadParams<HistoryKey>): LoadResult<HistoryKey, RoomEvent> {
        return try {
            val url = "${host.url}/hollywood/v2/history".toHttpUrl().newBuilder()
                .addQueryParameter("limit", params.loadSize.coerceAtMost(100).toString())
                .addQueryParameter("visibility", if (selection.recipient == "room") "room" else "direct:${selection.recipient}")
            if (selection.task != "lobby") url.addQueryParameter("task", selection.task)
            params.key?.let { url.addQueryParameter(it.direction, it.id.toString()) }
            val response = repository.request("history?${url.build().encodedQuery}", host = host)
            val data = response.getJSONArray("data")
            val events = (0 until data.length()).map { RoomEvent.from(data.getJSONObject(it)) }
            if (params.key == null) onRecentPage(events)
            LoadResult.Page(
                data = events,
                prevKey = response.optLong("newerCursor").takeIf { it > 0 }?.let { HistoryKey("after", it) },
                nextKey = response.optLong("olderCursor").takeIf { it > 0 }?.let { HistoryKey("before", it) },
            )
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) {
            val recent = cached.filter { it.kind in chatKinds &&
                it.visibility == (if (selection.recipient == "room") "room" else "direct:${selection.recipient}") &&
                (selection.task == "lobby" || it.task == selection.task) }.sortedByDescending { it.id }.take(50)
            if (error is IOException && params is LoadParams.Refresh && params.key == null && recent.isNotEmpty())
                LoadResult.Page(recent, null, HistoryKey("before", recent.last().id))
            else LoadResult.Error(error)
        }
    }

    override fun getRefreshKey(state: PagingState<HistoryKey, RoomEvent>): HistoryKey? {
        val position = state.anchorPosition ?: return null
        // The latest page follows new messages; an older page refreshes around its visible message.
        if (position < 3 && state.pages.firstOrNull()?.prevKey == null) return null
        return state.closestItemToPosition(position)?.let { HistoryKey("around", it.id) }
    }
}
