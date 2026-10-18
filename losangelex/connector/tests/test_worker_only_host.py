"""Protected participant lookup on a worker-only host; no services or models."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lax_connector import collaboration_capture, service_memory, service_observer


@unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "Requires administrator-owned protected-record fixtures")
class WorkerOnlyHostTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.authority = "4a415e93-7f74-4acd-aa4a-5432b13a0800"
        self.agent = "1cccd9fe-730f-438f-9ebc-27df75f5dbaf"
        self.host = "68033529-af23-49c8-9d5f-698807434100"
        self.root = Path(self.temp.name)
        self.base = self.root / self.authority
        record = self.base / "workers" / self.agent
        record.mkdir(parents=True)
        self.home = record / "home"
        self.home.mkdir()
        self.spec = {"authorityId": self.authority, "agentId": self.agent,
                     "hostId": self.host, "binary": "/approved/native"}
        self.receipt = {"authorityId": self.authority, "agentId": self.agent,
                        "unit": "lax-worker-fixture.service"}
        (record / "provision-intent.json").write_text(json.dumps({"spec": self.spec}))
        (record / "provision-receipt.json").write_text(json.dumps(self.receipt))
        def namespace(value):
            return self.root if str(value) == "/var/lib/harness" else Path(value)
        for module in (service_memory, service_observer, collaboration_capture):
            p = patch.object(module, "Path", side_effect=namespace)
            p.start()
            self.addCleanup(p.stop)

    def test_worker_identity_and_native_capture_need_no_global(self):
        account = SimpleNamespace(pw_uid=12345, pw_dir=str(self.home))
        with patch.object(service_observer.pwd, "getpwnam", return_value=account), \
             patch.object(collaboration_capture.pwd, "getpwuid", return_value=account), \
             patch.object(service_observer, "properties",
                          return_value={"Id": self.receipt["unit"]}):
            self.assertEqual(service_memory.approved_spec(self.authority, self.agent),
                             (self.spec, self.receipt, False))
            self.assertEqual(service_observer.expected_owner(self.authority, self.agent),
                             (12345, self.home, "/approved/native"))
            self.assertEqual(service_observer.installed_unit(self.authority, self.agent),
                             self.receipt["unit"])
            self.assertEqual(collaboration_capture.installed_native_owner(self.authority, 12345),
                             (self.agent, "/approved/native"))
        self.assertFalse((self.base / "global-admin-receipt.json").exists())
        self.assertFalse((self.base / "global-admin-intent.json").exists())

    def test_existing_unprotected_global_receipt_cannot_be_ignored(self):
        p = self.base / "global-admin-receipt.json"
        p.write_text("{}")
        p.chmod(0o666)
        with self.assertRaises(PermissionError):
            service_memory.approved_spec(self.authority, self.agent)

    def test_worker_record_cannot_select_another_principal(self):
        p = self.base / "workers" / self.agent / "provision-intent.json"
        p.write_text(json.dumps({"spec": {**self.spec, "agentId": self.authority}}))
        with self.assertRaises(PermissionError):
            service_observer.expected_owner(self.authority, self.agent)


if __name__ == "__main__":
    unittest.main()
