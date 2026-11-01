"""Maintenance uses real protected release metadata, not an arbitrary new Python.

Existing disposable release fixture supplies synthetic service/canonical facts.
No systemd, installed worker, native process, auth or provider is accessed.
"""
import hashlib
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from lax_connector import room_host_inspection as maintenance, linux_worker
import test_native_release as release_fixture


@unittest.skipUnless(os.geteuid() == 0, 'Root-protected disposable release required')
class FactoryMaintenanceTests(unittest.TestCase):
    setUp = release_fixture.ReleaseTests.setUp
    get = release_fixture.ReleaseTests.get
    probe_release = release_fixture.ReleaseTests.probe_release
    prepare = release_fixture.ReleaseTests.prepare
    approve = release_fixture.ReleaseTests.approve

    def test_original_spec_inspected_only_by_accepted_current_maintenance_closure(self):
        module = self.new_root/'inspection-fixture.py'
        module.write_bytes(b'UNEXECUTED fixture maintenance-module identity')
        module.chmod(0o644)
        self.prepare(); self.approve()
        original = {'authorityId': self.authority, 'hostId': self.host,
                    'agentId': str(uuid4()), 'interpreter': str(self.python)}
        file = self.root/'original-spec.private.json'
        raw = (json.dumps(original, indent=2)+'\n').encode()
        file.write_bytes(raw); file.chmod(0o600)
        sha = hashlib.sha256(raw).hexdigest()
        receipt = {'authorityId': self.authority, 'agentId': original['agentId'],
                   'inspection': {'setupRepeated': False, 'modelOrServiceRestarted': False}}
        def inspect_without_owner_lock(spec):
            with release_fixture.image.registry_lock(self.registry):
                return receipt
        with patch.object(maintenance, '__file__', str(module)), \
             patch.object(maintenance, 'sys', SimpleNamespace(executable=str(self.new_python))), \
             patch.object(linux_worker, 'inspect_completed', side_effect=inspect_without_owner_lock) as inspect:
            result = maintenance.inspect_original(file, self.agent, sha)
            inspect.assert_called_once_with(original)
            self.assertEqual(result['maintenanceRuntime']['interpreter'], str(self.new_python))
            self.assertNotEqual(result['maintenanceRuntime']['interpreter'], original['interpreter'])
            self.assertEqual(result['maintenanceRuntime']['originalSpecSha256'], sha)
            self.assertEqual(file.read_bytes(), raw)
            with self.assertRaisesRegex(ValueError, 'specification CAS'):
                maintenance.inspect_original(file, self.agent, '0'*64)
            with patch.object(maintenance, 'sys', SimpleNamespace(executable='/unreviewed/python')):
                with self.assertRaisesRegex(PermissionError, 'accepted release'):
                    maintenance.inspect_original(file, self.agent, sha)
            self.assertEqual(inspect.call_count, 1)
            module.write_bytes(module.read_bytes()+b' changed')
            with self.assertRaisesRegex(ValueError, 'asset identity changed'):
                maintenance.inspect_original(file, self.agent, sha)
            self.assertEqual(inspect.call_count, 1)
        self.assertEqual(file.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
