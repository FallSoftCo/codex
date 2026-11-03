"""Only the generated receipt short name is normalized; all pins still bind."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lax_connector import kernel_incarnation as kernel
from lax_connector import native_release, service_observer as observer, service_restart


class ManagedUnitReceipt(unittest.TestCase):
    def test_original_short_and_canonical_receipts_keep_exact_enrollment_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            image = home / 'native'
            image.write_bytes(b'identity-only, never executed')
            info = image.stat()
            baseline = {'schema': 'lax-service-enrollment/v1', 'authorityId': 'authority',
                'hostId': 'host', 'agentId': 'agent', 'uid': 123, 'home': str(home),
                'unit': 'lax-worker-authority-agent.service', 'unitDefinitionDigest': 'd' * 64,
                'binary': str(image), 'binaryDevice': info.st_dev, 'binaryInode': info.st_ino,
                'machineIdentity': 'machine', 'killMode': 'control-group'}
            binding = {**baseline, 'schema': 'lax-service-incarnation/v1', 'bootId': 'boot'}
            receipt = {'unit': 'lax-worker-authority-agent'}
            with (patch.object(observer, 'expected_owner', return_value=(123, home, image)),
                  patch.object(observer, 'directory', return_value=home),
                  patch.object(observer, 'protected', return_value=baseline),
                  patch.object(observer, 'machine_identity', return_value='machine'),
                  patch.object(observer, 'boot_id', return_value='boot'),
                  patch.object(observer, 'properties', side_effect=AssertionError('No manager lookup')) as manager,
                  patch.object(native_release, 'runtime_spec', return_value=({'interpreter': '/python'}, receipt, True)),
                  patch.object(kernel, '_guardian', return_value={'pid': 456}) as guardian,
                  patch.object(service_restart, 'validate_approval') as approval):
                for spelling in ('lax-worker-authority-agent', 'lax-worker-authority-agent.service'):
                    receipt['unit'] = spelling
                    self.assertEqual(kernel.managed_guardian(binding), {'pid': 456})
                    approval.assert_called_with('authority', 'host', 'agent', baseline, {'pid': 456})
                for spelling in ('other', 'lax-other', 'lax-worker-authority-agent.timer',
                                 'lax-worker-authority-agent/../alias', 'lax-worker-authority-agent.service.service'):
                    receipt['unit'] = spelling
                    with self.assertRaises(PermissionError):
                        kernel.managed_guardian(binding)
                receipt['unit'] = 'lax-worker-authority-agent'
                for field, changed in (('uid', 124), ('hostId', 'other-host'), ('home', '/other'),
                                       ('unitDefinitionDigest', 'e' * 64), ('binaryInode', info.st_ino + 1),
                                       ('killMode', 'mixed'), ('machineIdentity', 'other-machine')):
                    broken = copy.deepcopy(binding)
                    broken[field] = changed
                    with self.assertRaises(PermissionError):
                        kernel.managed_guardian(broken)
                broken = {**binding, 'bootId': 'old-boot'}
                with self.assertRaises(kernel.Unavailable):
                    kernel.managed_guardian(broken)
                self.assertEqual(guardian.call_count, 2)
                self.assertEqual(approval.call_count, 2)
                manager.assert_not_called()


if __name__ == '__main__':
    unittest.main()
