"""Local runtime-owned rollout readback; internal connector API, never a tool.

Trust the registered local runtime and its protected state, not model paths or
root-administrator or same-execution-UID resistance (including model commands).
A positive read proves persisted input only.
"""

import hashlib
import json
import os
from pathlib import Path
import stat

from .passive_context import Journal, Held, need, sha, uuid

MAX_TAIL_BYTES = 262144
MAX_LINE_BYTES = 65536
MAX_TAIL_RECORDS = 256


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "DUPLICATE_NATIVE_FIELD")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise Held("BAD_NATIVE_RECORD") from None


class RolloutReadback:
    def __init__(self, directory, *, binding, codex_home, registered_host_id):
        self.binding = dict(binding)
        self.host = uuid(registered_host_id)
        self.home = Path(codex_home)
        need(
            self.home.is_absolute() and self.home.resolve(strict=True) == self.home,
            "NONLOCAL_NATIVE_HOME",
        )
        s = self.home.lstat()
        need(
            stat.S_ISDIR(s.st_mode)
            and s.st_uid == os.geteuid()
            and not s.st_mode & 0o077,
            "UNPROTECTED_NATIVE_HOME",
        )
        self.journal = Journal(directory)
        self.locator = None

    def check_capture(self, captured):
        need(captured["delivery"].get("host") == self.host, "NONLOCAL_NATIVE_HOST")

    def _open(self, path):
        # The locator comes only from an owner RPC reply. Even that locator must
        # remain in this local runtime's configured sessions store, without links.
        path = Path(path)
        need(path.is_absolute() and ".." not in path.parts, "BAD_NATIVE_LOCATOR")
        try:
            parts = path.relative_to(self.home).parts
        except ValueError:
            raise Held("NATIVE_STORE_ESCAPE") from None
        need(
            len(parts) >= 2 and parts[0] == "sessions" and path.suffix == ".jsonl",
            "UNSUPPORTED_NATIVE_STORE",
        )
        fd = os.open(self.home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                os.close(fd)
                fd = child
                s = os.fstat(fd)
                need(
                    s.st_uid == os.geteuid() and not s.st_mode & 0o022,
                    "UNPROTECTED_NATIVE_STORE",
                )
            result = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                s = os.fstat(result)
                need(
                    stat.S_ISREG(s.st_mode)
                    and s.st_uid == os.geteuid()
                    and s.st_nlink == 1
                    and not s.st_mode & 0o022,
                    "UNPROTECTED_NATIVE_FILE",
                )
            except BaseException:
                os.close(result)
                raise
            return result
        finally:
            os.close(fd)

    def _identity(self, fd):
        s = os.fstat(fd)
        first = os.pread(fd, MAX_LINE_BYTES + 1, 0).split(b"\n", 1)
        need(
            len(first) == 2 and len(first[0]) <= MAX_LINE_BYTES,
            "NATIVE_META_UNAVAILABLE",
        )
        meta = decode(first[0])
        need(
            isinstance(meta, dict) and meta.get("type") == "session_meta",
            "BAD_NATIVE_META",
        )
        return s, meta.get("payload", {}), digest(first[0] + b"\n")

    def bind_native(self, reply, *, fresh=False):
        """Only call with thread/start, resume or metadata read's actual reply."""
        thread = reply.get("thread", {})
        need(
            thread.get("id") == self.binding["threadId"]
            and thread.get("ephemeral") is False,
            "NATIVE_THREAD_CHANGED",
        )
        uuid(thread.get("sessionId"))
        path = thread.get("path")
        need(
            isinstance(path, str) and 0 < len(path) <= 400, "NATIVE_LOCATOR_UNAVAILABLE"
        )
        value = {
            "schema": "lax-local-rollout-binding/v1",
            "binding": self.binding,
            "hostId": self.host,
            "home": str(self.home),
            "path": path,
            "sessionId": thread["sessionId"],
            "cwd": thread["cwd"],
        }
        try:
            fd = self._open(path)
        except FileNotFoundError:
            # Fresh thread/start is lazily materialized by this native version.
            # Only its actual reply can establish absence as a zero-byte origin.
            # A resumed/deleted store cannot acquire this privilege retroactively.
            prior = self.journal.get("fresh-origin.json")
            need(fresh or prior == value, "EXISTING_NATIVE_STORE_ABSENT")
            need(self.journal.get("file-identity.json") is None, "NATIVE_FILE_CHANGED")
            self.journal.put("binding.json", value, immutable=True)
            self.journal.put("fresh-origin.json", value, immutable=True)
            self.locator = value
            return
        else:
            os.close(fd)
        self.journal.put("binding.json", value, immutable=True)
        self.locator = value
        fd, _ = self._bound_file()
        os.close(fd)

    def _bound_file(self):
        need(self.locator is not None, "NATIVE_NOT_BOUND")
        fd = self._open(self.locator["path"])
        try:
            s, meta, meta_sha = self._identity(fd)
            need(
                meta.get("id") == self.binding["threadId"]
                and meta.get("session_id") == self.locator["sessionId"]
                and meta.get("cwd") == self.locator["cwd"],
                "NATIVE_SESSION_CHANGED",
            )
            identity = {"device": s.st_dev, "inode": s.st_ino, "metaSha256": meta_sha}
            old = self.journal.get("file-identity.json")
            need(old is None or old == identity, "NATIVE_FILE_CHANGED")
            self.journal.put("file-identity.json", identity, immutable=True)
            return fd, s
        except BaseException:
            os.close(fd)
            raise

    def prepare(self, event_id, item):
        """Durably fix an EOF offset BEFORE receiver intent or any injection."""
        uuid(event_id)
        try:
            fd, s = self._bound_file()
        except FileNotFoundError:
            need(
                self.journal.get("fresh-origin.json") == self.locator,
                "EXISTING_NATIVE_STORE_ABSENT",
            )
            self.journal.phase(
                event_id,
                "00-origin",
                {
                    "eventId": event_id,
                    "itemSha256": sha(item),
                    "locator": self.locator,
                    "offset": 0,
                    "expectedAbsent": True,
                    "boundarySha256": digest(b""),
                },
            )
            return
        try:
            need(
                s.st_size > 0 and os.pread(fd, 1, s.st_size - 1) == b"\n",
                "NATIVE_TAIL_INCOMPLETE",
            )
            origin = {
                "eventId": event_id,
                "itemSha256": sha(item),
                "locator": self.locator,
                "offset": s.st_size,
                "boundarySha256": digest(
                    os.pread(fd, min(128, s.st_size), max(0, s.st_size - 128))
                ),
            }
            self.journal.phase(event_id, "00-origin", origin)
        finally:
            os.close(fd)

    def probe(self, intent):
        """Finite exact tail read; missing, partial, over-budget or ambiguous holds.

        No search before the protected origin offset, no guessed thread/items
        projection, no resend. Reopen revalidates the same inode/meta/raw line.
        """
        event_id = uuid(intent["eventId"])
        need(
            intent["binding"] == self.binding
            and sha(intent["item"]) == intent["itemSha256"],
            "READBACK_SCOPE_CHANGED",
        )
        origin = self.journal.phase(event_id, "00-origin")
        need(
            origin
            and origin["locator"] == self.locator
            and origin["itemSha256"] == intent["itemSha256"],
            "NATIVE_ORIGIN_UNAVAILABLE",
        )
        try:
            fd, s = self._bound_file()
        except FileNotFoundError:
            return None
        try:
            offset = origin["offset"]
            need(
                type(offset) is int
                and 0 <= offset <= s.st_size
                and (offset > 0 or origin.get("expectedAbsent") is True),
                "NATIVE_TAIL_LOST",
            )
            need(
                digest(os.pread(fd, min(128, offset), max(0, offset - 128)))
                == origin["boundarySha256"],
                "NATIVE_ORIGIN_CHANGED",
            )
            old = self.journal.phase(event_id, "01-proof")
            if old:
                raw = old["rawLineUtf8"].encode()
                need(
                    old["binding"] == self.binding
                    and old["item"] == intent["item"]
                    and old["fileIdentity"]
                    == {**self.locator, **self.journal.get("file-identity.json")}
                    and os.pread(fd, len(raw), old["byteStart"]) == raw,
                    "NATIVE_PROOF_CHANGED",
                )
                return old
            need(s.st_size - offset <= MAX_TAIL_BYTES, "NATIVE_TAIL_BUDGET")
            tail = os.pread(fd, s.st_size - offset, offset)
            need(len(tail) == s.st_size - offset, "NATIVE_TAIL_LOST")
            if tail and not tail.endswith(b"\n"):
                return None
            records = tail.splitlines(keepends=True)
            need(len(records) <= MAX_TAIL_RECORDS, "NATIVE_TAIL_BUDGET")
            found = []
            cursor = offset
            for raw in records:
                need(
                    len(raw) <= MAX_LINE_BYTES and raw.endswith(b"\n"),
                    "NATIVE_LINE_BUDGET",
                )
                record = decode(raw)
                need(isinstance(record, dict), "BAD_NATIVE_RECORD")
                payload = record.get("payload", {})
                if (
                    record.get("type") == "response_item"
                    and isinstance(payload, dict)
                    and payload.get("id") == event_id
                ):
                    expected = intent["item"]
                    # These are the ONLY fields the pinned native history writer
                    # adds. Retain them in full; never drop unknown raw fields.
                    metadata = payload.get("internal_chat_message_metadata_passthrough")
                    if metadata is not None:
                        need(
                            isinstance(metadata, dict)
                            and set(metadata) == {"turn_id", "create_time"}
                            and isinstance(metadata["turn_id"], str)
                            and 0 < len(metadata["turn_id"]) <= 128
                            and type(metadata["create_time"]) in (int, float)
                            and metadata["create_time"] > 0,
                            "UNEXPECTED_NATIVE_METADATA",
                        )
                        expected = {
                            **expected,
                            "internal_chat_message_metadata_passthrough": metadata,
                        }
                    need(payload == expected, "NATIVE_ITEM_NOT_EXACT")
                    found.append((cursor, raw, payload))
                cursor += len(raw)
            need(len(found) <= 1, "AMBIGUOUS_NATIVE_ITEM")
            if not found:
                return None
            start, raw, payload = found[0]
            evidence = {
                "schema": "lax-passive-native-readback/v1",
                "binding": self.binding,
                "eventId": event_id,
                "item": intent["item"],
                "persisted": True,
                "nativeJournalLocator": str(
                    self.journal.root / "events" / event_id / "01-proof.json"
                ),
                "fileIdentity": {
                    **self.locator,
                    **self.journal.get("file-identity.json"),
                },
                "byteStart": start,
                "byteEnd": start + len(raw),
                "scanStart": offset,
                "scanEnd": s.st_size,
                "persistedRawItem": payload,
                "rawLineUtf8": raw.decode(),
                "rawLineSha256": digest(raw),
                "modelConsumptionProved": False,
            }
            self.journal.phase(event_id, "01-proof", evidence)
            return evidence
        finally:
            os.close(fd)
