# Use the shared team room

Run `losangelex-room` on the host for one terminal conversation with the project team. Start
with the coordinator, address `Maya, …` or `@theo …` publicly, or reply to a particular message.
Choose a direct recipient for a private conversation. The task and recipient stay visible next
to the composer, and each conversation keeps its own draft.

The native Android app provides the same shared conversation, replies and direct conversations.
Its foreground connection streams events. Background alerts use Firebase; the app does not keep
a terminal or polling connection alive in Android's background.

## Install on this Linux host

From the renewed Losangelex checkout, after testing the candidate:

```sh
python3 losangelex/pin_room.py \
  --hollywood-source /home/ai/Development/hollywood-next \
  --workspace /home/ai/Development --workspace-mode shared \
  --codex /home/ai/.local/share/losangelex/candidates/f8ab57359dde6b6d5de1aee613c18fe60b661aeb/package/bin/codex \
  --firebase-project losangelex \
  --firebase-credentials /absolute/private/application_default_credentials.json
losangelex-room
```

Omit both Firebase options when testing the room without push. The app explicitly reports that
notifications are not configured. The installer shares `~/.codex/auth.json` by reference; it
does not require another Codex login or copy credentials. Its runtime home contains separate
configuration and state. User skills and rules are shared. Other user configuration and plugins
are not imported automatically in this first release; `--model` selects the model.

The host service is `hollywood-room.service`; its state is `~/.local/state/hollywood-room`.
Installed packages and dependency receipts live under `~/.local/share/losangelex/room-releases`.
The existing `losangelex`, `losangelex-next` and legacy Hollywood service remain available.
For a host that must continue after logout, enable its user service manager with
`loginctl enable-linger "$USER"` (an administrator may need to run this). Lingering is enabled
on this development host.

The installed project root is `/home/ai/Development`, including its subfolders and repositories.
Agents work directly in the folder you name, for example `hollywood-next` or
`losangelex-next/losangelex/android`. Changes in this shared mode appear in those actual folders;
there is no automatic copy to integrate. Independent task conversations share the filesystem,
so teammates must coordinate overlapping edits and preserve existing work. Their instructions
require reading applicable nested `AGENTS.md` files before editing a subproject.

The original single-repository behavior remains available with `--workspace-mode worktree`.
Changing root or mode takes effect at an idle runtime restart. Existing conversations resume
at the configured root; old worktrees and their uncommitted changes remain available.

## Conversation and control

- “Coordinator, create notification-check and have Maya implement it; ask Rowan to review.”
- “Maya, explain the tradeoff.” Addressing a name in the shared room remains public.
- “Coordinator, work in hollywood-next and update its room API; have Theo review the changed files.”
- Reply to an agent's task message to continue in that task's conversation.
- Select **Direct** to redirect a teammate privately. Committed changes are summarized to the
  coordinator through Hollywood; the full conversation is kept separate.
- “Coordinator, pause Maya in notification-check.” To resume: “Resume Maya in notification-check.”
- **Stop** sends an immediate control request for the selected agent/task without a model turn.
  It interrupts current work and pauses subsequent automatic work until resumed.
- **Needs you** shows questions and approvals in the TUI. Android notifications open the current
  request, including whether another client has already handled it.

Messages and answers retain a command ID before submission. A connection failure keeps the
original body, task and recipient for retry. Switching to another draft does not retarget the
pending message. Approvals show the concrete command or change and cannot revive after expiry.

## Android connection

The signed release APK on this host is available privately at
[Download Losangelex 0.2.0](https://system76-pc.tailb77f2a.ts.net:8446/android/losangelex-0.2.0.apk).
Connect Tailscale on the phone, install the APK, open it and allow notifications. In **Connection & notifications**,
use `https://system76-pc.tailb77f2a.ts.net:8446` and the token file described below.

The signed release is installed and paired on the owner's Pixel 9 Pro Fold. Notification
permission is granted, and a [physical-device test](evidence/android-physical-phone.json)
verified background delivery, opening the private question, and answering it from the app.
Version 0.1.1 added the [Hollywood Hills launcher icon](android/artwork/README.md), including
a themed monochrome variant. Its signed update retained the phone's connection and notification
registration; the room service continued running during the update.

Version 0.2.0 adds [the chat interface](android/CHAT_UX.md): distinct teammate avatars and roles,
message bubbles, quoted replies, mention suggestions, and progressive access to the complete
conversation history. Its signed update is installed on the Pixel with the same certificate.
The [chat release record](evidence/android-chat-release.json) includes native interaction and
visual tests, long-history scrolling, and a repeated real Firebase Doze check on the emulator.

Build the native app in `losangelex/android` with `./gradlew :app:assembleDebug`. Register
`co.fallsoft.losangelex` in Firebase and put its downloaded `google-services.json` in `app/`;
that host-specific configuration is ignored by Git. The build also works without Firebase
configuration for local UI development. Android 8 or newer is supported; background push uses
Google Play services and notification permission.

Use your private HTTPS host URL and the access token in
`~/.local/state/hollywood-room/client-token` in the app's **Connection & notifications** dialog. The token stays in
Android Keystore-backed encrypted storage. The release network policy rejects cleartext HTTP;
debug builds allow only the emulator bridge and loopback for integration tests. A TLS reverse
proxy can also provide a public endpoint; initial deployment uses the private connection.
The host and encrypted credential are stored together. In-flight requests retain their original
host/credential pair when the connection changes.

Notification payloads contain only opaque attention and device-registration IDs. The lock screen shows a generic alert;
opening it retrieves task details from the authenticated host. If the private connection is
temporarily unavailable, the notification still arrives and its target is retained for reconnect.
Normal Android restrictions still apply, including denied notification permission and force-stop.
Registrations are scoped to the connected host; an alert from a previous host cannot open a
different task after switching hosts.

For this development host, use ADC with service-account impersonation and a notification-only
identity. No service-account private key is required. For unattended deployment on other hosts,
use their workload identity or federation where available. The server accepts Google ADC files.

Release builds use `LOSANGELEX_SIGNING_PROPERTIES` pointing to a private Java properties file
containing `storeFile`, `storePassword`, `keyAlias` and `keyPassword`. On this host that file is
`~/.local/state/hollywood-room/credentials/android-signing/signing.properties`; retain its keystore
for future APK updates. It is outside the repository. Build with:

```sh
LOSANGELEX_SIGNING_PROPERTIES=/absolute/private/signing.properties ./gradlew :app:assembleRelease :app:lintRelease
```

## Developing while using it

Continue using the installed packages while changing either checkout. Rebuilds write candidate
artifacts, and rerunning the installer leaves the active service running on its existing release.
Clients can disconnect and reconnect while model turns continue. Test server changes with a
separate state directory and port. When the installed service is idle, explicitly restart it to
select the new package; existing threads resume from their persisted history.

An in-flight model turn cannot survive destruction of its host process. This implementation
removes client restarts and source rebuilds from that process's lifetime. It does not hot-patch
workers or promise uninterrupted turns across host crashes.

## Reproduce the proof

```sh
cd losangelex/room-client
uv sync --locked
uv run pytest -q
cd ../android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
```

Hollywood's `tests/evaluate_room.py` and `tests/evaluate_lifecycle.py` exercise the actual model,
not a simulated coordinator. The latter opens the real TUI, redirects a running turn, closes
the TUI, rebuilds its wheel, reconnects, checks the resulting file, restarts the idle runtime and
asks the model to recall an earlier instruction. See [the captured evidence](evidence/README.md).

With the debug app and test APK installed and connected on a disposable emulator, reproduce the
real model/Firebase/Doze/notification-navigation test with:

```sh
python3 losangelex/android/prove_push.py --serial emulator-5582 \
  --url http://127.0.0.1:18766 \
  --token-file ~/.local/state/hollywood-room/client-token \
  --output /tmp/new-android-proof.json
```

The script waits for Doze to settle, asks the real teammate a fixed test question, checks actual
Android receipt and priority, and runs the three native integration tests. It restores the
emulator's battery/idle state. Its question stays open for inspection and can be answered in the room.

Current scope is one configured root per service, which can contain multiple repositories,
and a fixed team of four agents with separate conversations for each task. Aggregation of
independently configured roots, arbitrary team setup,
automatic integration of worktree changes, and migration of legacy sessions are not implemented.
These checks establish the listed behaviors; they do not establish general superiority over Codex.
