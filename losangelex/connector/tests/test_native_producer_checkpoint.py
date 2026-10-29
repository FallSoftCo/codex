"""Native record-format controls; no model or execution-authority claim."""
import copy
import hashlib
import json
import unittest

from lax_connector.native_context_checkpoint import (
    canonical_native, verify_checkpoint)


class CompleteProducerCheckpointTests(unittest.TestCase):
    def checkpoint(self):
        thread, context = "thread", "context"
        window = "497477fd-549e-86fa-a90b-e33528cbb7cc"
        base = [{"type": "message", "role": "developer",
                 "content": [{"type": "input_text", "text": "native role"}]}]
        source = {"schema": "lax-native-context-producer/v1",
                  "producer_revision": "native-reviewed-revision",
                  "thread_id": thread, "context_id": context,
                  "reference": {"turn_id": "original"},
                  "acquired_step": {"turn_id": "original"},
                  "template": {"snapshot": {"tools": ["read", "write"]}}}
        source_sha = hashlib.sha256(json.dumps(source, sort_keys=True,
            ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        native = {"schema": "lax-native-context-checkpoint/v1", "thread_id": thread,
                  "context_id": context, "mode": "idle_request",
                  "reference_context": source["reference"],
                  "world_state": {"full": True, "state": source["template"]["snapshot"],
                      "native_context_producer": {"source": source, "sha256": source_sha}}}
        data = [{"type": "function_call_output", "name": "context_refill",
                 "output": json.dumps({"content": "selected facts"})}]
        compact = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        group_sha = hashlib.sha256(compact(base)).hexdigest()
        metadata = [{"client_authored": False, "native_context_origin": {
            "schema": "lax-native-core-context/v1", "thread_id": thread,
            "context_id": context, "group_id": window, "kind": "prefix",
            "index": 0, "count": 1, "sha256": group_sha}}, {"client_authored": False}]
        body = {"window_id": window, "replacement_history": base + data,
                "replacement_history_metadata": metadata,
                "resume_metadata": {"last_started_turn_id": "original", "native_context": native}}
        preflight = {"producerSha256": source_sha,
                     "state": {"producerSha256": source_sha}, "nextWindowId": window,
                     "operationId": "original-op", "prefixItemCount": 1,
                     "replacementItemCount": 2,
                     "replacementWireBytes": len(compact(base + data)),
                     "replacementSha256": hashlib.sha256(json.dumps(base + data,
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        request = {"threadId": thread, "contextId": context, "turnId": "original",
                   "operationId": "original-op"}
        return body, base, request, {"items": data}, preflight

    def verify(self, body, base, request, response, preflight):
        raw = json.dumps({"type": "compacted", "payload": body},
                         ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        return verify_checkpoint(raw, body, base, request, response, "idle_request",
                                 preflight=preflight)

    def test_complete_producer_exact_reviewed_target_is_admitted(self):
        self.verify(*self.checkpoint())

    def test_changed_producer_review_or_target_is_refused(self):
        for change in ("source", "reviewed_hash", "state_hash", "target", "replacement_hash", "missing_review"):
            with self.subTest(change=change):
                body, base, request, response, preflight = self.checkpoint()
                if change == "source":
                    body["resume_metadata"]["native_context"]["world_state"]["native_context_producer"]["source"]["template"]["snapshot"]["extra"] = True
                elif change == "reviewed_hash":
                    preflight["producerSha256"] = "b" * 64
                elif change == "state_hash":
                    preflight["state"]["producerSha256"] = None
                elif change == "target":
                    preflight["nextWindowId"] = "597477fd-549e-86fa-a90b-e33528cbb7cc"
                elif change == "replacement_hash":
                    preflight["replacementSha256"] = "c" * 64
                else:
                    preflight = None
                with self.assertRaises(RuntimeError):
                    self.verify(body, base, request, response, preflight)

    def test_native_number_and_unicode_encoding_survive_object_sort(self):
        raw = '{"z":1e-7,"a":{"é":"value","b":[1.0,-0.0,1e+20]}}'
        expected = '{"a":{"b":[1.0,-0.0,1e+20],"é":"value"},"z":1e-7}'
        self.assertEqual(canonical_native(raw), expected.encode())
