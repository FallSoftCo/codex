# Android conversations

Version 0.2.0 turns the room into a chat interface. The team and each teammate have consistent
avatars and colors, with names and roles on incoming messages. Your messages appear on the
right. The header and conversation picker distinguish shared and private conversations.

Reviewed native previews: [team room](app/src/androidTest/assets/screenshots/team-room.png)
and [private reply](app/src/androidTest/assets/screenshots/direct-reply.png).

Tap a teammate to open their conversation, or tap the conversation title to choose one.
Choose a task to narrow its history. Long-press a message to reply, copy it, or open its author's
private conversation. Replies show a source excerpt above the composer; the close button
cancels the reply without deleting the draft. The `@` button offers teammate names and places
an address at the start of a public message. Choosing a mention clears an existing reply so
its previous addressee cannot silently override the newly selected teammate.

The composer supports multiple lines, a send button, and Ctrl/Command+Enter with a hardware
keyboard. Drafts remain separate by host, task, and conversation. An unconfirmed submission
shows its original text and recipient; retry keeps its original command ID and destination,
even after switching conversations. Confirming it preserves a different draft and reply.
The roster makes room for messages while the software keyboard is open.

History opens at the newest messages and loads older pages as you scroll. A new arrival keeps
an older message at its current position. **Latest** returns to the newest page. Notifications
can open a message by its ID without fetching all preceding history. The server retains the
complete durable history; Android uses 50-message pages and Jetpack Paging with a 250-item
memory target. The existing bounded cache keeps recent messages available offline; older,
uncached pages require a connection and have an explicit retry action.

The API change is additive. Existing TUI and forward-replay clients keep their interfaces.
Installing or rebuilding the Android app does not restart agents. The history endpoint was
activated after checking the installed runtime was idle; existing threads and events were retained.

## Repeat the checks

From the Hollywood checkout, run the isolated fixture server (it never starts agents or sends push):

```sh
uv run --extra room python /path/to/losangelex-next/losangelex/android/fixtures/history_server.py
```

Build `:app:assembleDebug :app:assembleDebugAndroidTest`, install both APKs on the
`losangelex-room-api35` emulator, then run:

```sh
adb -s emulator-5582 shell am instrument -w \
  -e class co.fallsoft.losangelex.RoomHistoryTest,co.fallsoft.losangelex.RoomUiTest,co.fallsoft.losangelex.RoomDraftTest,co.fallsoft.losangelex.ChatUiTest,co.fallsoft.losangelex.ChatPagingTest \
  -e historyServerUrl http://10.0.2.2:18768 \
  -e roomServerUrl http://10.0.2.2:18768 \
  co.fallsoft.losangelex.test/androidx.test.runner.AndroidJUnitRunner
```

The fixture has over 650 public messages and distinct private conversations. Tests exercise
all pages, cache fallback, captured host credentials, source-bound replies, cross-conversation
retry and draft retention, mentions, and a live arrival after scrolling to the beginning with
old pages evicted. These are transport and UI assertions, not simulated evidence about model judgment.

Visual snapshots live in `app/src/androidTest/assets/screenshots/`. They use the API 35 emulator
at 1080×2340, 440 dpi, English, font scale 1, and America/New_York time. To update intentionally,
add `-e recordScreenshots true`, pull `files/team-room.png` and `files/direct-reply.png` with
`adb exec-out run-as co.fallsoft.losangelex cat`, inspect them, and replace the expected assets.
The screenshot test compares the rendered pixels; run the other interaction tests on additional
device sizes separately. The screenshots contain explicit fixture messages rather than a user's history.

The separate `prove_push.py` runner retains the three native API/reply/notification acceptance
tests and uses an explicitly selected disposable emulator for the real Firebase replay.

Implementation references: [Android Paging](https://developer.android.com/topic/libraries/architecture/paging/v3-paged-data)
and [stable lazy-list keys](https://developer.android.com/develop/ui/compose/lists).
