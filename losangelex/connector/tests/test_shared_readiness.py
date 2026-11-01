"""Protected shared-account readiness; kernel/systemd facts are synthetic.

Real metadata validation, NSS guard and package subprocess construction run.
No service, native thread, account auth or external process is started.
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from lax_connector import shared_account as shared, service_admin as admin
from lax_connector import service_observer as observer, service_memory, service_restart, service_runtime
from lax_connector import native_package as package
from lax_connector.journal import saved
import test_shared_account as fixtures


@unittest.skipUnless(os.geteuid() == 0, 'Root-protected disposable fixture required')
class SharedReadinessTests(unittest.TestCase):
    setUp = fixtures.SharedAccountTests.setUp
    bind = fixtures.SharedAccountTests.bind

    def test_registered_attachment_reaches_package_probe_with_original_nss_profile(self):
        home, bound = self.bind(self.spec)
        saved(home/'connector.json', {'synthetic': True})
        uid = self.account.pw_uid
        info = {'Id': 'synthetic.service', 'ActiveState': 'active', 'MainPID': '42',
                'ControlGroup': '/synthetic', 'InvocationID': uuid4().hex}
        guardian = {'pid': 42, 'uid': uid, 'controlGroup': '/synthetic', 'start': 'synthetic'}
        image = self.binary.stat()
        baseline = {'schema': 'lax-service-enrollment/v1', 'authorityId': self.authority,
                    'hostId': self.host, 'agentId': self.spec['agentId'], 'uid': uid, 'home': str(home),
                    'unit': info['Id'], 'unitDefinitionDigest': 'synthetic-definition',
                    'binary': str(self.binary), 'binaryDevice': image.st_dev, 'binaryInode': image.st_ino,
                    'machineIdentity': 'synthetic-machine', 'killMode': 'control-group'}
        registry = self.root/'service-registry'; registry.mkdir(mode=0o700)
        saved(registry/'enrollment.json', baseline)
        saved(registry/(info['InvocationID']+'.json'), {**baseline, 'schema': 'lax-service-incarnation/v1',
              'bootId': 'synthetic-boot', 'serviceInvocation': info['InvocationID'],
              'controlGroup': info['ControlGroup'], 'guardianPid': 42, 'guardianStart': 'synthetic'})
        receipt = {'uid': uid, 'linuxUser': self.account.pw_name}
        for name, value in {'installed_unit': info['Id'], 'properties': info, 'process': guardian,
                            'unit_definition': baseline['unitDefinitionDigest'], 'machine_identity': 'synthetic-machine',
                            'boot_id': 'synthetic-boot', 'directory': registry}.items():
            self.enterContext(patch.object(observer, name, return_value=value))
        self.enterContext(patch('lax_connector.purpose_observer.installation', return_value=None))
        self.enterContext(patch.object(service_memory, 'approved_spec', return_value=(self.spec, receipt, False)))
        self.enterContext(patch.object(service_memory, 'inspection', return_value={'synthetic': True}))
        self.enterContext(patch.object(service_restart, 'inspection', return_value={'enabled': True}))
        self.enterContext(patch.object(service_runtime, 'require_configured_guardian', return_value={'synthetic': True}))
        ready = {'schema': package.SCHEMA, 'ready': True, 'uid': uid, 'modelsStarted': 0,
                 'assets': {'entrypoint': {'sha256': 'synthetic-image'}}}
        with patch.object(package.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(ready))) as probe:
            result = admin.inspect(self.authority, self.host, self.spec['agentId'])
        self.assertTrue(result['ready'], result)
        self.assertEqual(result['reason'], 'execution-registration-ready')
        self.assertEqual(probe.call_args.kwargs['cwd'], home/'work')
        env = probe.call_args.kwargs['env']
        self.assertEqual((env['HOME'], env['CODEX_HOME']), (str(self.home), str(self.home/'codex-home')))
        self.assertEqual(probe.call_args.args[0][2], self.account.pw_name)
        self.assertEqual(probe.call_args.args[0][4], self.spec['interpreter'])
        self.assertFalse((home/'codex-home').exists())
        # The low-level NSS rule remains strict, and a missing/mismatched shared
        # receipt cannot fall back to that logical home or another UID.
        with patch.object(package.subprocess, 'run') as spawn:
            with self.assertRaisesRegex(package.PackageError, 'differs from NSS'):
                package.preflight_as_owner(self.binary, self.spec['interpreter'], uid, home)
            spawn.assert_not_called()
        with self.assertRaisesRegex(PermissionError, 'execution UID'):
            shared.package_context(self.spec, uid+1, home)
        (home.parent/'shared-native-account.json').unlink()
        with self.assertRaisesRegex(ValueError, 'receipt unavailable'):
            shared.package_context(self.spec, uid, home)

    def test_private_legacy_context_has_no_shared_home_exception(self):
        self.assertEqual(shared.package_context({}, 0, self.home), (self.home, {}))
        with patch.object(package.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps({'schema': package.SCHEMA, 'uid': 0, 'ready': True}))) as probe:
            package.preflight_as_owner(self.binary, '/synthetic/python', 0, self.home)
        self.assertEqual(probe.call_args.kwargs['cwd'], self.home/'work')
        self.assertEqual(probe.call_args.kwargs['env']['HOME'], str(self.home))


if __name__ == '__main__':
    unittest.main()
