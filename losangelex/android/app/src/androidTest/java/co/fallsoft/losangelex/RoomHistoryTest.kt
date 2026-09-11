package co.fallsoft.losangelex

import androidx.paging.PagingConfig
import androidx.paging.PagingSource
import androidx.paging.PagingState
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class RoomHistoryTest {
    @Test fun progressivePagesKeepEveryMessageAndRestoreAnOlderAnchor() = runBlocking {
        val url = InstrumentationRegistry.getArguments().getString("historyServerUrl")
        assumeTrue("Requires the isolated long-history server", url != null)
        val repository = RoomRepository(InstrumentationRegistry.getInstrumentation().targetContext)
        repository.credentials.connect(url!!, "android-fixture")
        val selection = HistorySelection(url, "lobby", "room", null, 0)
        val source = RoomHistorySource(repository, repository.credentials.read(), selection)
        val first = source.load(PagingSource.LoadParams.Refresh(null, 50, false)) as PagingSource.LoadResult.Page
        val ids = first.data.map { it.id }.toMutableList()
        var page = first
        while (page.nextKey != null) {
            page = source.load(PagingSource.LoadParams.Append(page.nextKey!!, 50, false)) as PagingSource.LoadResult.Page
            assertTrue(page.data.all { it.visibility == "room" })
            ids.addAll(page.data.map { it.id })
        }
        assertTrue(ids.size > 650)
        assertEquals(ids.sortedDescending().distinct(), ids)
        assertEquals(1L, ids.last())
        val around = source.load(PagingSource.LoadParams.Refresh(HistoryKey("around", 250), 50, false)) as PagingSource.LoadResult.Page
        assertTrue(around.data.any { it.id == 250L })
        val anchor = source.getRefreshKey(PagingState(listOf(around), 20, PagingConfig(50), 0))
        assertEquals(HistoryKey("around", around.data[20].id), anchor)
        assertNull(source.getRefreshKey(PagingState(listOf(first), 0, PagingConfig(50), 0)))
        val private = RoomHistorySource(repository, repository.credentials.read(), selection.copy(recipient = "theo"))
            .load(PagingSource.LoadParams.Refresh(null, 50, false)) as PagingSource.LoadResult.Page
        assertTrue(private.data.isNotEmpty())
        assertTrue(private.data.all { it.visibility == "direct:theo" })
    }

    @Test fun historyFailureCanRetryAndKeepsItsOriginalHost() = runBlocking {
        val url = InstrumentationRegistry.getArguments().getString("historyServerUrl")
        assumeTrue("Requires the isolated long-history server", url != null)
        val repository = RoomRepository(InstrumentationRegistry.getInstrumentation().targetContext)
        repository.credentials.connect(url!!, "android-fixture")
        val original = repository.credentials.read()
        val selection = HistorySelection(url, "lobby", "room", null, 0)
        val source = RoomHistorySource(repository, original, selection)
        repository.credentials.connect("http://127.0.0.1:1", "another-host")
        try {
            val page = source.load(PagingSource.LoadParams.Refresh(null, 50, false)) as PagingSource.LoadResult.Page
            assertTrue(page.data.isNotEmpty())
            val unavailable = RoomHistorySource(repository, repository.credentials.read(), selection)
            assertTrue(unavailable.load(PagingSource.LoadParams.Refresh(null, 50, false)) is PagingSource.LoadResult.Error)
            val offline = RoomHistorySource(repository, repository.credentials.read(), selection, page.data)
                .load(PagingSource.LoadParams.Refresh(null, 50, false)) as PagingSource.LoadResult.Page
            assertEquals(page.data, offline.data)
            val retry = source.load(PagingSource.LoadParams.Refresh(null, 50, false)) as PagingSource.LoadResult.Page
            assertEquals(page.data, retry.data)
        } finally { repository.credentials.connect(original.url, original.token) }
    }
}
