"""Protected bridge substrate tests; no native/controller/model execution proof."""
import hashlib
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lax_connector.collaboration_bridge import Bridge, Held, canonical_relative, read_file, receive, strict_json, digest


class NativeBoundaryTests(unittest.TestCase):
    def test_literal_paths_and_component_traversal(self):
        for value in ["a/b.rs", "percent%_name.rs", "space name.rs"]:
            self.assertEqual(canonical_relative(value), value)
        for value in ["", "/absolute", "a/../b", "a//b", "a/./b", "a\\b", "a:b", "e\u0301.rs", "a\x00b"]:
            with self.subTest(value=repr(value)), self.assertRaises(Held):
                canonical_relative(value)

    def test_descriptor_reads_preserve_absence_and_reject_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "actual").write_bytes(b"before\n")
            self.assertEqual(read_file(root, "actual"), {"relativePath": "actual", "sha256": hashlib.sha256(b"before\n").hexdigest(), "size": 7})
            self.assertEqual(read_file(root, "missing/child"), {"relativePath": "missing/child", "sha256": "absent", "size": 0})
            (root / "alias").symlink_to(root / "actual")
            with self.assertRaises(OSError):
                read_file(root, "alias")
            with self.assertRaises(Held):
                read_file(root, "../actual")

    def test_frame_duplicate_identity_and_truncated_transport(self):
        with self.assertRaises(Held):
            strict_json('{"tool":"apply_patch","tool":"coordination_act"}')
        bridge = object.__new__(Bridge)
        frame = {"schema": "lax-native-collaboration-rpc/v1", "agentId": "forged"}
        with self.assertRaises(Held):
            bridge.captured((1234, 1000, 1000), frame)
        left, right = socket.socketpair()
        with left, right:
            left.sendall(b"abc")
            left.shutdown(socket.SHUT_WR)
            with self.assertRaises(Held):
                receive(right, 4)


    def test_unregistered_peer_is_refused_before_frame_read(self):
        import struct
        bridge=object.__new__(Bridge)
        listener,connection=MagicMock(),MagicMock()
        listener.__enter__.return_value=listener
        connection.__enter__.return_value=connection
        connection.getsockopt.return_value=struct.pack("3i",1234,1000,1000)
        listener.accept.side_effect=[(connection,None),EOFError("stop fixture listener")]
        with tempfile.TemporaryDirectory() as tmp, \
                patch("lax_connector.collaboration_bridge.socket.socket",return_value=listener), \
                patch("lax_connector.collaboration_bridge.protected_directory"), \
                patch("lax_connector.collaboration_bridge.process",return_value=None), \
                patch("lax_connector.collaboration_bridge.receive") as frame_read, \
                patch.object(Path,"chmod"), patch.object(bridge,"handle") as relay:
            with self.assertRaises(EOFError):
                bridge.serve(Path(tmp)/"fixture.sock")
            frame_read.assert_not_called()
            relay.assert_not_called()
            response=connection.sendall.call_args.args[0][4:]
            self.assertFalse(json.loads(response)["success"])


    def test_model_reply_bound_preserves_original_record_without_relay_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"commands").mkdir();info=root.stat()
            bridge=object.__new__(Bridge);bridge.state=root
            work="30000000-0000-0000-0000-000000000001"
            plan="40000000-0000-0000-0000-000000000001"
            record={"ports":["edit-plans"],"work":{"id":work},"sourceBase":{"agentId":"owner"},
                    "resources":[{"environmentId":"local","root":str(root),"device":info.st_dev,"inode":info.st_ino,"workspaceId":"physical"}]}
            bridge.captured=lambda *args:(record,{"tool":"collaborative_edit_plan"},{"editPlans":True,"physicalTargets":True,"bridge":{"protocol":"canonical-edit-plans/v2"}})
            recorded=[]
            def relay(*args):
                recorded.append(args)
                return {"receipt":{"accepted":True},"detail":"x"*9000}
            bridge.relay=relay
            frame={"port":"edit-plans","arguments":{"command":{"action":"propose","workId":work,"planId":plan,"manifest":{"files":[]}}},"evidence":{"environmentId":"local","cwd":root.as_uri()}}
            with self.assertRaisesRegex(Held,"effect may already be recorded"):
                bridge.handle((1234,1000,1000),frame)
            self.assertEqual(len(recorded),1)
            pointer=bridge.plan_pointer(record,record["resources"][0])
            self.assertEqual(json.loads(pointer.read_text()),{"planId":plan})


class PhysicalAttestationTests(unittest.TestCase):
    def test_shared_root_identity_is_separate_from_private_context_and_revoked_grants_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file").write_bytes(b"before")
            info = root.stat()
            host = "10000000-0000-0000-0000-000000000001"
            physical = {"hostId":host, "environmentId":"local", "root":str(root),
                        "device":info.st_dev, "inode":info.st_ino,
                        "workspaceId":"20000000-0000-0000-0000-000000000001"}
            env = digest({"hostId":host,"environmentId":"local"})
            row = {"id":physical["workspaceId"],"root_path":str(root),"host":host,
                   "environment_sha256":env,"root_identity_sha256":digest({"hostId":host,"environmentSha256":env,"device":info.st_dev,"inode":info.st_ino}),
                   "revision":1,"grant_revision":2}
            bridge = object.__new__(Bridge)
            bridge.config = {"hostId":host}
            bridge.http = lambda *args: {"workRevision":3,"targets":[row]}
            body = {"command":{"workId":"30000000-0000-0000-0000-000000000001","workRevision":3},"source":{"contextId":"private-a"}}
            a = bridge.attestation({"native":{"pid":os.getpid()}},body,physical,["file"])
            body["source"]["contextId"] = "private-b"
            b = bridge.attestation({"native":{"pid":os.getpid()}},body,physical,["file"])
            self.assertEqual(a["workspaceId"],b["workspaceId"])
            self.assertNotEqual(a["actionDigest"],b["actionDigest"])
            self.assertEqual(a["paths"],[{"relativePath":"file","resolvedPath":str(root/"file")}])
            row["root_identity_sha256"] = "0"*64
            with self.assertRaises(Held):
                bridge.attestation({"native":{"pid":os.getpid()}},body,physical,["file"])
            row["root_identity_sha256"] = a["rootIdentitySha256"]
            (root/"alias").symlink_to(root/"file")
            with self.assertRaises(OSError):
                bridge.attestation({"native":{"pid":os.getpid()}},body,physical,["alias"])

    def test_revision_read_and_changed_head(self):
        from lax_connector.collaboration_resources import revision
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/".git/refs/heads").mkdir(parents=True)
            (root/".git/HEAD").write_text("ref: refs/heads/main\n")
            (root/".git/refs/heads/main").write_text("a"*40+"\n")
            self.assertEqual(revision(root),"a"*40)
            (root/".git/refs/heads/main").write_text("b"*40+"\n")
            self.assertEqual(revision(root),"b"*40)
            (root/".git/refs/heads/main").unlink()
            (root/".git/refs/heads/main").symlink_to(root/".git/HEAD")
            with self.assertRaises(OSError):
                revision(root)


class OriginalReceiptTests(unittest.TestCase):
    def setup_bridge(self, root, http):
        bridge = object.__new__(Bridge)
        bridge.state = root
        (root / "commands").mkdir()
        bridge.http = http
        # Journal-only fixture: physical attestation is separately exercised.
        bridge.attestation = lambda *args: {"schema": "synthetic-journal-target"}
        record = {"bridgeRevision": 1, "executorId": "20000000-0000-0000-0000-000000000001", "descriptorDigest": "a" * 64, "serviceBindingDigest": "b" * 64}
        source = {"agentId": "30000000-0000-0000-0000-000000000001", "nativeThread": "thread", "nativeTurn": "turn", "callId": "call", "tool": "apply_patch"}
        return bridge, record, source

    def test_unknown_post_is_inspected_without_repeating_and_changed_body_holds(self):
        calls = []
        def http(method, route, body=None):
            calls.append((method, route))
            if method == "POST":
                raise TimeoutError("lost accepted response")
            return {"acceptedResult": {"mayApply": False, "accepted": True}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge, record, source = self.setup_bridge(root, http)
            with patch("lax_connector.collaboration_bridge.protected", lambda path: json.loads(path.read_text())):
                with self.assertRaises(TimeoutError):
                    bridge.relay(record, source, "patch-begin", {"action": "begin"})
                replay = bridge.relay(record, source, "patch-begin", {"action": "begin"})
                self.assertEqual(replay, {"receipt": {"mayApply": False, "accepted": True}, "admission": None, "replayed": True})
                with self.assertRaises(Held):
                    bridge.relay(record, source, "patch-begin", {"action": "begin", "note": "changed"})
        self.assertEqual([method for method, _ in calls], ["POST", "GET"])

    def test_original_begin_grant_is_never_reissued_from_local_receipt(self):
        calls = []
        def http(method, route, body=None):
            calls.append(method)
            return {"receipt": {"mayApply": False}, "admission": {"mayApply": True, "permitRevision": 2}, "replayed": False}
        with tempfile.TemporaryDirectory() as tmp:
            bridge, record, source = self.setup_bridge(Path(tmp), http)
            with patch("lax_connector.collaboration_bridge.protected", lambda path: json.loads(path.read_text())):
                first = bridge.relay(record, source, "patch-begin", {"action": "begin"})
                second = bridge.relay(record, source, "patch-begin", {"action": "begin"})
                self.assertTrue(first["admission"]["mayApply"])
                self.assertIsNone(second["admission"])
                self.assertTrue(second["replayed"])
        self.assertEqual(calls, ["POST"])


if __name__ == "__main__":
    unittest.main()
