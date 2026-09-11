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
| [Physical Android installation](android-physical-phone.json) | Signed release installed on a Pixel 9 Pro Fold running Android 16; installed APK hash verified and notification permission granted |
| [Native Android answer](android-answer.json) | The native composer answered question 27; the host resolved it and kept the answer in `direct:theo` |
| [Build and installation](build-and-install.json) | 35 backend tests, 5 terminal tests with 3 snapshots, signed non-debuggable release APK, existing Codex sign-in shared, installed runtime preserved across client installation |

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

Notification transport remains subject to Android and Firebase delivery behavior. The signed
release is installed on the physical Pixel 9 Pro Fold through the user-provided wireless ADB
endpoint. Pairing and notification receipt on that phone are pending its owner unlocking the
screen. The background receipt and navigation results above are from the disposable emulator.

## Visual records

- [Actual generic Android notification](android-notification.png): no private question text.
- [Actual private question on Android](android-private-question.png): source, recipient and answer action.
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
