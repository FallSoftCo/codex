"""Seven bounded local guard checks; fixtures are not native-behavior evidence."""

import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from lax_connector.passive_context import Held, sha
from lax_connector.passive_readback import RolloutReadback, MAX_TAIL_BYTES


class ReadbackGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        (self.home / "sessions").mkdir(mode=0o700)
        self.thread = str(uuid4())
        self.host = str(uuid4())
        self.event = str(uuid4())
        self.binding = {
            "authorityId": str(uuid4()),
            "principalId": str(uuid4()),
            "contextId": "a" * 64,
            "threadId": self.thread,
        }
        self.path = self.home / "sessions" / "fixture.jsonl"
        self.path.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": self.thread,
                        "session_id": self.thread,
                        "cwd": str(self.root),
                    },
                }
            )
            + "\n"
        )
        self.path.chmod(0o600)
        self.reply = {
            "thread": {
                "id": self.thread,
                "sessionId": self.thread,
                "ephemeral": False,
                "cwd": str(self.root),
                "path": str(self.path),
            }
        }
        self.p = RolloutReadback(
            self.root / "journal",
            binding=self.binding,
            codex_home=self.home,
            registered_host_id=self.host,
        )
        self.p.bind_native(self.reply)
        self.item = {
            "type": "agent_message",
            "id": self.event,
            "author": str(uuid4()),
            "recipient": self.binding["principalId"],
            "content": [{"type": "input_text", "text": "fixture"}],
        }
        self.intent = {
            "eventId": self.event,
            "binding": self.binding,
            "item": self.item,
            "itemSha256": sha(self.item),
        }

    def append(self, item):
        with self.path.open("a") as f:
            f.write(json.dumps({"type": "response_item", "payload": item}) + "\n")

    def test_wrong_host_and_store_escape(self):
        with self.assertRaisesRegex(Held, "NONLOCAL_NATIVE_HOST"):
            self.p.check_capture({"delivery": {"host": str(uuid4())}})
        with self.assertRaisesRegex(Held, "NATIVE_STORE_ESCAPE"):
            self.p.bind_native(
                {
                    "thread": {
                        **self.reply["thread"],
                        "path": str(self.root / "other.jsonl"),
                    }
                }
            )

    def test_only_fresh_native_start_can_record_absent_origin(self):
        data = self.path.read_bytes()
        self.path.unlink()
        fresh = RolloutReadback(
            self.root / "fresh-journal",
            binding=self.binding,
            codex_home=self.home,
            registered_host_id=self.host,
        )
        with self.assertRaisesRegex(Held, "EXISTING_NATIVE_STORE_ABSENT"):
            fresh.bind_native(self.reply)
        fresh.bind_native(self.reply, fresh=True)
        fresh.prepare(self.event, self.item)
        self.assertEqual(fresh.journal.phase(self.event, "00-origin")["offset"], 0)
        self.assertIsNone(fresh.probe(self.intent))
        self.path.write_bytes(data)
        self.path.chmod(0o600)
        self.append(self.item)
        proof = fresh.probe(self.intent)
        self.assertEqual(proof["persistedRawItem"], self.item)
        self.assertEqual(proof["scanStart"], 0)

    def test_original_offset_required_and_absent_stays_held(self):
        self.append(self.item)
        with self.assertRaisesRegex(Held, "NATIVE_ORIGIN_UNAVAILABLE"):
            self.p.probe(self.intent)
        self.p.prepare(self.event, self.item)
        self.assertIsNone(self.p.probe(self.intent))  # No historical match.

    def test_same_id_wrong_content_is_not_proof(self):
        self.p.prepare(self.event, self.item)
        self.append({**self.item, "content": []})
        with self.assertRaisesRegex(Held, "NATIVE_ITEM_NOT_EXACT"):
            self.p.probe(self.intent)

    def test_duplicate_raw_items_are_ambiguous(self):
        self.p.prepare(self.event, self.item)
        self.append(self.item)
        self.append(self.item)
        with self.assertRaisesRegex(Held, "AMBIGUOUS_NATIVE_ITEM"):
            self.p.probe(self.intent)

    def test_tail_budget_and_partial_record_hold(self):
        self.p.prepare(self.event, self.item)
        with self.path.open("ab") as f:
            f.write(b"{")
        self.assertIsNone(self.p.probe(self.intent))
        with self.path.open("ab") as f:
            f.write(b" " * MAX_TAIL_BYTES)
        with self.assertRaisesRegex(Held, "NATIVE_TAIL_BUDGET"):
            self.p.probe(self.intent)

    def test_replaced_inode_and_symlink_refuse(self):
        self.p.prepare(self.event, self.item)
        data = self.path.read_bytes()
        self.path.rename(self.path.with_suffix(".old"))
        self.path.write_bytes(data)
        self.path.chmod(0o600)
        with self.assertRaisesRegex(Held, "NATIVE_FILE_CHANGED"):
            self.p.probe(self.intent)
        self.path.unlink()
        self.path.symlink_to(self.path.with_suffix(".old"))
        with self.assertRaises(OSError):
            self.p.probe(self.intent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
