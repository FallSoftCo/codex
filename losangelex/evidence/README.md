# Captured room proof

These are observed runs from September 10–11, 2026. The model was `gpt-6-astra`, using
the packaged Codex binary built from upstream `f8ab57359dde6b6d5de1aee613c18fe60b661aeb`.
The reports preserve transcripts, checks and binary hashes. They establish the listed
behaviors; they are not a comparative productivity benchmark against Codex.

| Evidence | Result |
| --- | --- |
| [Room model run](room-model.json) | 15/15 checks: direct addressing, peer handoff, private brief, independent task contexts, real delegated artifact, correct task follow-up, durable question and answer |
| [Session lifecycle run](session-lifecycle.json) | 7/7 checks: steer a live turn, close the actual TUI, rebuild its wheel, reconnect, verify the corrected file, restart the idle runtime and recover prior context |
| [Android background replay](android-background.json) | 5/5 checks, including real Firebase receipt in Doze and all 3 native integration tests over private HTTPS |
| [Physical Android run](android-physical-phone.json) | 17/17 checks on the signed release: private HTTPS pairing, actual background notification, notification tap opening the exact private question, and native answer persisted and resolved by the host |
| [Native Android answer](android-answer.json) | The native composer answered question 27; the host resolved it and kept the answer in `direct:theo` |
| [Build and installation](build-and-install.json) | 39 backend tests, 5 terminal tests with 3 snapshots, signed non-debuggable release APK, existing Codex sign-in shared, installed runtime preserved across client installation |
| [Shared development root](shared-workspace-model.json) | 11/11 real-model checks: same thread and memory after changing root, edits in two nested repositories, per-folder instructions, preserved existing changes, and delegated repository selection |
| [Installed root verification](shared-root-install.json) | 8/8 checks: idle activation retained existing thread bindings; the existing Maya conversation verified `/home/ai/Development` and wrote/read a temporary nested file there without a scope approval |
| [Android icon update](../android/artwork/release.json) | Version 0.1.1: release build and lint passed, signed APK installed and visually reviewed on the Pixel, connection and notification registration retained, host service stayed running |
| [Android chat update](android-chat-release.json) | Version 0.2.0 installed on the Pixel: 9 native tests, 2 visual snapshots, 47 backend tests, progressive history beyond 650 messages with preserved reading position, and a repeated real Firebase Doze replay on the emulator |

The [chat UI snapshots](../android/CHAT_UX.md) use native Compose rendering with explicit fixtures.
The [nine-test output](android-chat-tests.txt) covers messaging, paging, drafts and retries;
the separate [Firebase replay](android-chat-push.json) passed five checks and its three native
acceptance tests. Version 0.2.0's installed APK hash, certificate and notification permission
were verified on the Pixel. Screenshots and interaction tests for this release came from the
emulator. The earlier physical UI and notification records below remain evidence for version 0.1.0.

The icon update is recorded separately from the Android behavior runs, which used version 0.1.0.
Its [artwork previews and physical-device screenshot](../android/artwork/README.md) show the new
Hollywood Hills icon; the background-notification behavior suites were not repeated for this change.

The shared-root update adds `--workspace-mode shared`. The installed root is now
`/home/ai/Development`, with direct access to its named subfolders. The isolated evaluation
used frozen copies of actual room documentation in two repositories under a non-Git parent.
Existing conversations remained independent and remembered earlier context. The final installed
check used the real host and then removed its temporary proof files. Shared mode does not provide
automatic file locks; teammates must coordinate overlapping edits. The earlier worktree-mode
proofs below remain records of that supported mode. No Android code or APK changed for this update.

The lifecycle run retained the same process, thread and turn identifiers while its client was
rebuilt. The model obeyed a correction delivered during the running shell command: the resulting
file contained `AFTER`, rather than the original `BEFORE`. After an idle host restart it recalled
the earlier phrase `CEDAR-481`. This does not claim that an in-flight turn survives destruction
of its host process.

The room run produced [this actual delegated file](notification-contract.txt). A coordinator
assigned it to Maya, and the worker wrote the requested content in its task worktree. The
private-context fixture checks that the coordinator receives the permitted task brief without
the full private conversation. These are live model observations; conversation separation is
not operating-system isolation between hostile agents.

The final Android replay waited 30 seconds after entering Doze, then submitted a real question
through Hollywood. The app recorded receipt while Android remained `IDLE`, at delivered and
original priority `1` (high). Receipt was approximately two seconds after the recorded question
timestamp. The tests then opened the actual notification intent in the existing activity,
checked its private conversation and question identity, and exercised authenticated requests,
idempotent sends, and retained host/credential pairs when configuration changes.

[Earlier Android runs](android-prior-runs.json) are included to avoid hiding a delayed delivery:
one alert arrived about 87 seconds after the question, following a device wake. Later Doze runs
delivered at high priority without waking the device out of Doze. An earlier navigation test also
found missing activity routing; that was fixed. A subsequent test teardown failure was traced to
ActivityScenario matching the original launch intent after `onNewIntent` replaced it; the test
now restores that bookkeeping after its behavior assertions. The final replay includes the
passing instrumentation output.

The signed release is installed and paired on the physical Pixel 9 Pro Fold running Android 16.
With the app in the background, a real Theo question triggered a generic Android notification,
observed within four seconds of the question timestamp. Tapping the actual notification opened
question 88 in `direct:theo`. The native composer sent the test answer; the host persisted it in
the same private conversation and resolved the question. This run used the normal home screen,
without changing battery settings or forcing Doze. The app was relaunched once after initial
pairing before Firebase registration completed; the cause of that initial registration delay
was not established. Notification transport remains subject to Android and Firebase delivery
behavior. The separate emulator runs above cover forced Doze.

## Visual records

- [Actual generic Android notification](android-notification.png): no private question text.
- [Actual private question on Android](android-private-question.png): source, recipient and answer action.
- [Private question on the physical Pixel](android-physical-question.png): the signed release after tapping its actual notification.
- [Installed terminal client](tui-installed.svg): live API connection and replay.
- [TUI after reconnecting to the lifecycle test](tui-reconnected.svg).
- [Wide](tui-wide.svg) and [narrow](tui-narrow.svg) layout fixtures; these are explicitly labeled previews.

The APK certificate and verification output are in [the release signature record](android-release-signature.txt).
Signing keys, host tokens, Codex credentials, Firebase credentials and device installation IDs
are excluded from these artifacts. The signed APK is distributed over the private Tailscale
endpoint, not committed to Git.

## Reproduce

See [ROOM.md](../ROOM.md) for installation and Android replay commands. Hollywood contains
`tests/evaluate_room.py` and `tests/evaluate_lifecycle.py`; both keep the actual model in the loop.
Use disposable worktrees and an installed binary. The Android runner requires the debug app and
test APK on a disposable emulator, an authenticated room, and the configured Firebase sender.

Source branches: [Losangelex](https://github.com/FallSoftCo/codex/tree/losangelex-next) and
[Hollywood](https://github.com/FallSoftCo/hollywood/tree/shared-team-room).

Relevant provider guidance: [Firebase message priority](https://firebase.google.com/docs/cloud-messaging/android-message-priority)
and [Android Doze testing](https://developer.android.com/training/monitoring-device-state/doze-standby).
