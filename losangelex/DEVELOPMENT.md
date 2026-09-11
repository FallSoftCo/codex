Daily use and development
=========================

On the investigated Linux machine:

| Command/location | Purpose |
| --- | --- |
| `losangelex` | Pinned legacy Hollywood runtime; startup does not build |
| `losangelex-next` | Packaged September 10 upstream Codex baseline |
| `losangelex-room` | Installed shared Hollywood team room, with native Android access |
| `/home/ai/Development/losangelex` | Legacy source and reference implementation |
| `/home/ai/Development/losangelex-next` | New integration branch based on upstream `f8ab57359d` |

The candidate has its own runtime home under `~/.local/share/losangelex/candidates/f8ab57359dde6b6d5de1aee613c18fe60b661aeb/codex-home`. Its authentication file now links to the existing `~/.codex/auth.json`; another login is unnecessary. Historical sessions and runtime databases remain separate. Its `0.0.0` version string is the upstream source-tree version; the adjacent `build-receipt.json` records the exact upstream commit and package hashes.

The new [shared room](ROOM.md) runs as `hollywood-room.service` on loopback port 18766. It uses the same Codex sign-in and owns model threads independently of terminal and Android clients. See [the captured proof](evidence/README.md) for a live turn surviving a TUI rebuild and actual Android delivery during Doze.

To snapshot another tested legacy build, run from this checkout:

```bash
python3 losangelex/pin_legacy.py \
  --source /home/ai/Development/losangelex \
  --binary /home/ai/Development/losangelex/codex-rs/target/losangelex-launcher/debug/codex
```

This changes the default for new invocations. Running clients and servers retain their release paths. Keep earlier releases until their sessions finish. Validate database compatibility before selecting a different executable. The previous local command wrapper is retained as `~/.local/bin/losangelex.before-pin-*`.

Build a new candidate into a new package directory. Run from the candidate repository root:

```bash
just assemble-codex-package --target x86_64-unknown-linux-gnu \
  --package-dir /absolute/path/to/new-candidate-package
uv run --with websocket-client==1.7.0 python \
  losangelex/smoke_runtime.py /absolute/path/to/new-candidate-package/bin/codex
```

The smoke creates disposable state and checks app-server readiness plus client reconnection without submitting a model turn. Runtime snapshots use only Python's standard library; the smoke additionally uses `websocket-client` (1.7.0 was the version exercised locally). Pin build provenance and run broader product evaluations before adopting a candidate for daily use. Do not overwrite a package used by running sessions.

Hollywood's next service start uses a non-editable installation under `~/.local/share/losangelex/hollywood/54bca57317bc3c949b8bd35fde5f1dca6284f640/`. The active service was left running. Its systemd selection is in `~/.config/systemd/user/hollywood.service.d/10-pinned-runtime.conf`; the original unit is intact. An intentional rollback can remove this drop-in and reload systemd, but stopping or restarting the service is a separate operation that affects connected sessions.

For Hollywood development, use an explicit separate database and loopback port:

```bash
python3 /home/ai/Development/hollywood/hollywood.py serve \
  --host 127.0.0.1 --port 18765 --db /absolute/path/to/candidate-hollywood.db
```

Keep the daily `8765` service and its `~/.hollywood/hollywood.db` for existing sessions. The installed `losangelex-next` wrapper keeps legacy Hollywood auto-attach disabled; use `losangelex-room` for the new shared room. See [the investigation](RENEWAL.md) for the architecture, migration stages, and performance acceptance criteria.
