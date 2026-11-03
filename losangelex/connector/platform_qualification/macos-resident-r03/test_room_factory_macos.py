"""Resident-host platform files only; no native/model/service admission fixture."""
import copy
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from uuid import uuid4
from lax_connector import room_factory_macos as f
from lax_connector.room_tools import TOOLS
from lax_connector import room_bootstrap

ROOT = Path.home() / '.local/state/mfrqa'


class ResidentFilesTests(unittest.TestCase):
    def setUp(self):
        self.umask = os.umask(0o077)
        ROOT.mkdir(mode=0o700, exist_ok=True)
        f.trusted(ROOT, private=True, directory=True)
        self.b = Path(tempfile.mkdtemp(prefix='c-', dir=ROOT))
        for name in ('profile', 'native', 'parent-state', 'parent-work', 'agents', 'operation'):
            (self.b / name).mkdir(mode=0o700)
        (self.b / 'profile/auth.json').write_text('SYNTHETIC_NO_AUTH_COPY')
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(self.b / 'native/n.sock'))
        (self.b / 'native/n.sock').chmod(0o600)
        self.ids = {k: str(uuid4()) for k in ('authorityId', 'originRoomId', 'agentId', 'hostId')}
        self.scope = {**self.ids, 'nodeId': self.ids['hostId'], 'operationId': 'original-logical-session-operation'}
        self.owner = str(uuid4())
        self.parentthread = str(uuid4())
        self.native = {'pid': 100, 'uid': os.geteuid(), 'birth': 'native-original', 'image': str(Path(sys.executable).resolve())}
        self.parent = {'pid': 101, 'uid': os.geteuid(), 'birth': 'parent-original', 'image': str(Path(sys.executable).resolve())}
        self.processes = {100: self.native, 101: self.parent}
        self.manifest = {'schema': 'lax-native-host/v1', 'runtimeMode': 'room-conversation', 'platform': 'darwin',
                         'authorityId': self.ids['authorityId'], 'hostId': self.ids['hostId'], 'ownerAgentId': self.owner,
                         'serviceUser': 'fixture', 'binary': sys.executable, 'codexHome': str(self.b / 'profile'),
                         'state': str(self.b / 'native'), 'workspace': str(self.b / 'parent-work'),
                         'unit': 'original-shared-native', 'socket': str(self.b / 'native/n.sock')}
        self.put(self.b / 'manifest.json', self.manifest)
        parent = {'authorityId': self.ids['authorityId'], 'hostId': self.ids['hostId'], 'agentId': self.owner,
                  'nativeThreadId': self.parentthread, 'state': str(self.b / 'parent-state'),
                  'workspace': str(self.b / 'parent-work'), 'nativeServer': {'manifest': str(self.b / 'manifest.json')},
                  'codexHome': str(self.b / 'profile'), 'binary': sys.executable, 'token': 'SYNTHETIC_PARENT_UNCHANGED'}
        self.put(self.b / 'parent.private.json', parent)
        self.put(self.b / 'owner.json', {'agentId': self.owner, 'nodeId': self.ids['hostId'],
                 'sharedNativeService': self.manifest['unit'], 'nativeThreadId': self.parentthread})
        self.home = self.b / 'agents' / self.ids['agentId']
        self.config = {'runtimeMode': 'room-conversation', **{k: self.ids[k] for k in ('authorityId', 'hostId', 'agentId')},
                       'nativeServer': parent['nativeServer'], 'codexHome': parent['codexHome'], 'binary': sys.executable,
                       'nativeName': 'Fresh role', 'instructions': 'Fresh origin role, not parent instructions.',
                       'conversationResumeInstructions': {'developerInstructions': 'Fresh origin role for resume.'},
                       'model': 'declared-model', 'effort': 'xhigh', 'token': 'SYNTHETIC_CHILD_TOKEN',
                       'hollywoodUrl': 'http://127.0.0.1:1', 'sandbox': 'danger-full-access', 'approvalPolicy': 'never',
                       'conversationDynamicTools': TOOLS, 'rooms': [{'roomId': self.ids['originRoomId'], 'after': 0}],
                       'state': str(self.home / 'state'), 'workspace': str(self.home / 'work')}
        self.policy = {'schema': 'lax-macos-room-account/v1', 'uid': os.geteuid(), 'user': 'fixture',
                       'serviceHome': str(self.b), 'initialPermissions': {'sandbox': 'danger-full-access', 'approvalPolicy': 'never'},
                       'authorityId': self.ids['authorityId'], 'hostId': self.ids['hostId'], 'ownerAgentId': self.owner,
                       'nativeManifest': self.pin(self.b / 'manifest.json'), 'parentConfig': self.pin(self.b / 'parent.private.json'),
                       'ownerReceipt': self.pin(self.b / 'owner.json'), 'agentRoot': str(self.b / 'agents'),
                       'agentRootIdentity': f.identity(self.b / 'agents'), 'nativeProcess': self.native,
                       'parentProcess': self.parent, 'interpreter': self.pin(Path(sys.executable).resolve()),
                       'binary': {'path': sys.executable, 'sha256': f.digest(Path(sys.executable).resolve().read_bytes())}}
        self.policyfile = self.b / 'policy.json'
        self.put(self.policyfile, self.policy)
        self.nss = patch.object(f.pwd, 'getpwuid', return_value=types.SimpleNamespace(pw_name='fixture', pw_dir=str(self.b)))
        self.nss.start()

    def tearDown(self):
        self.nss.stop()
        self.sock.close()
        shutil.rmtree(self.b)
        os.umask(self.umask)

    def put(self, p, v):
        p.write_text(json.dumps(v, indent=2))
        p.chmod(0o600)

    def pin(self, path):
        return {'path': str(path), 'sha256': f.digest(path.read_bytes())}

    def helper(self):
        return f.MacAgentFiles(self.policyfile, f.digest(self.policyfile.read_bytes()),
                               process_reader=lambda pid: copy.deepcopy(self.processes.get(pid)))

    def prepare(self, inspect=False):
        raw = json.dumps({**self.scope, 'connectorConfig': self.config}, indent=2).encode()
        return self.helper().prepare_files(self.config, self.scope, self.b / 'operation',
                                           raw_spec=raw, expected_spec_sha256=f.digest(raw), inspect=inspect)

    def test_prepare_inspect_idempotent_and_no_runtime_or_native_dispatch(self):
        hashes = {n: self.pin(self.b / n)['sha256'] for n in ('manifest.json', 'parent.private.json', 'owner.json', 'profile/auth.json')}
        result = self.prepare()
        self.assertTrue(result['sessionAttachmentRequired'])
        self.assertEqual(result['osServicesCreated'], 0)
        self.assertEqual(result['nativeThreadsCreated'], 0)
        self.assertEqual(result['modelTurnsRequested'], 0)
        self.assertNotIn('ready', result)
        self.assertEqual(result, self.prepare())
        self.assertEqual(result, self.prepare(inspect=True))
        cfg = Path(result['initialConfigPath'])
        self.assertEqual(f.digest(cfg.read_bytes()), result['initialConfigSha256'])
        self.assertEqual(json.loads(cfg.read_text()), self.config)
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.home / 'state').stat().st_mode & 0o777, 0o700)
        self.assertFalse((self.home / 'codex-home').exists())
        self.assertNotIn('SYNTHETIC_CHILD_TOKEN', json.dumps(result))
        for n, sha in hashes.items():
            self.assertEqual(self.pin(self.b / n)['sha256'], sha)

    def test_unknown_native_initialization_left_untouched(self):
        self.prepare()
        unknown = self.home / 'state/native-context.json'
        self.put(unknown, {'state': 'creating', 'threadStartAttempted': True, 'originalUncertain': True})
        original = unknown.read_bytes()
        self.prepare()
        self.prepare(inspect=True)
        self.assertEqual(unknown.read_bytes(), original)

    def test_original_origin_and_competing_directory_are_fenced(self):
        self.prepare()
        old = (self.home / 'initial-config.private.json').read_bytes()
        self.scope['originRoomId'] = str(uuid4())
        self.config['rooms'] = [{'roomId': self.scope['originRoomId'], 'after': 0}]
        with self.assertRaises(f.Hold):
            self.prepare()
        self.assertEqual((self.home / 'initial-config.private.json').read_bytes(), old)
        other = self.b / 'other'
        other.mkdir(mode=0o700)
        raw = json.dumps({**self.scope, 'connectorConfig': self.config}, indent=2).encode()
        with self.assertRaises(f.Hold):
            self.helper().prepare_files(self.config, self.scope, other, raw_spec=raw,
                                        expected_spec_sha256=f.digest(raw))

    def test_stopped_or_changed_parent_is_blocked_before_files(self):
        self.processes[101] = None
        with self.assertRaises(f.Hold):
            self.prepare()
        self.assertFalse(self.home.exists())
        self.processes[101] = {**self.parent, 'birth': 'replacement-incarnation'}
        with self.assertRaises(f.Hold):
            self.prepare()
        self.assertFalse(self.home.exists())

    def test_root_policy_and_original_profile_boundary(self):
        original = self.policyfile.read_bytes()
        self.policyfile.chmod(0o644)
        with self.assertRaises(f.Hold):
            self.prepare()
        self.policyfile.chmod(0o600)
        (self.b / 'agents').rename(self.b / 'held-original-root')
        (self.b / 'agents').mkdir(mode=0o700)
        with self.assertRaises(f.Hold):
            self.prepare()
        self.assertEqual(self.policyfile.read_bytes(), original)

    def test_config_and_later_native_policy_not_reasserted(self):
        self.prepare()
        self.config['approvalPolicy'] = 'on-request'
        with self.assertRaises(f.Hold):
            self.prepare()
        self.assertEqual(json.loads((self.home / 'initial-config.private.json').read_text())['approvalPolicy'], 'never')
        # Helper doesn't inspect/reapply durable thread settings; common/runtime
        # must retain a later explicit owner restriction in their original receipt.
        settings = self.home / 'state/owner-restriction.json'
        self.put(settings, {'sandbox': 'readOnly', 'approvalPolicy': 'on-request'})
        held = settings.read_bytes()
        self.config['approvalPolicy'] = 'never'
        self.prepare(inspect=True)
        self.assertEqual(settings.read_bytes(), held)

    def test_alias_private_spec_and_component_lock(self):
        self.prepare()
        claim = self.b / 'agents' / (self.ids['agentId'] + '.claim.json')
        original = claim.read_bytes()
        raw = json.dumps({**self.scope, 'connectorConfig': self.config}, indent=2).encode()
        helper = self.helper()
        with helper.lock(self.scope, self.b / 'operation', f.digest(raw), inspect=False):
            with self.assertRaises(BlockingIOError):
                self.prepare()
        self.assertEqual(claim.read_bytes(), original)
        cfg = self.home / 'initial-config.private.json'
        actual = self.home / 'held-config.json'
        cfg.rename(actual)
        cfg.symlink_to(actual)
        with self.assertRaises(f.Hold):
            self.prepare(inspect=True)

    def test_no_os_service_or_native_client_lifecycle_in_helper(self):
        import ast
        tree = ast.parse(Path(f.__file__).read_text())
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(names & {'bootstrap', 'bootout', 'kill', 'terminate', 'Popen', 'create_subprocess_exec'})
        text = Path(f.__file__).read_text()
        self.assertNotIn('launchctl', text)
        self.assertNotIn('subprocess', text)
        self.assertNotIn('thread/start', text)
        self.assertNotIn('thread/settings/update', text)
        self.assertNotIn('SharedAppServer', text)
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MacAgentFiles']
        self.assertEqual(len(classes), 1)
        self.assertNotIn('initialize', {n.attr for n in ast.walk(classes[0]) if isinstance(n, ast.Attribute)})


    def public_spec(self):
        guide = self.b / 'OPERATIONS.txt'
        guide.write_text('Approved fixture host resource guide.\n')
        guide.chmod(0o644)
        instruction = ' Fresh host guide ' + str(guide) + ' SHA256 ' + self.pin(guide)['sha256']
        self.config['instructions'] += instruction
        self.config['conversationResumeInstructions']['developerInstructions'] += instruction
        spec = {'schema': 'lax-room-origin-local-spec/v1', **self.scope,
                'connectorConfig': self.config, 'nativeHostManifestSha256': self.policy['nativeManifest']['sha256'],
                'nativeIdentity': self.native,
                'parentRuntime': {'agentId': self.owner, 'identity': self.parent, 'roomOriginPolicy': self.pin(self.policyfile)},
                'operatingInstructions': [self.pin(guide)]}
        self.publicfile = self.b / 'spec.private.json'
        self.put(self.publicfile, spec)
        self.rpc_calls = []
        self.thread = str(uuid4())
        self.transport_fail = False
        self.thread_lost = False
        case = self
        class RPC:
            async def start(self):
                case.rpc_calls.append('initialize')
                if case.transport_fail:
                    raise OSError('Synthetic transport unavailable')
            async def call(self, method, params):
                case.rpc_calls.append(method)
                if method == 'thread/start':
                    if case.thread_lost:
                        raise TimeoutError('SYNTHETIC_SECRET_MUST_NOT_ESCAPE')
                    return {'thread': {'id': case.thread}, 'sandbox': {'type': 'dangerFullAccess'}, 'approvalPolicy': 'never'}
                if method in ('thread/settings/update', 'thread/name/set'):
                    return {}
                raise AssertionError('Unexpected native operation ' + method)
            async def close(self):
                case.rpc_calls.append('close')
        self.public_patches = [patch.object(f.os, 'getpid', return_value=self.parent['pid']),
                               patch.object(f, 'process_identity', side_effect=lambda pid: copy.deepcopy(self.processes.get(pid))),
                               patch.object(room_bootstrap, 'native_client', side_effect=lambda *a: RPC())]
        for p in self.public_patches:
            p.start()
            self.addCleanup(p.stop)
        return spec

    def invoke_public(self, inspect=False):
        return asyncio.run(f.provision_local(self.publicfile, self.b / 'operation', inspect=inspect,
                                            expected_spec_sha256=self.pin(self.publicfile)['sha256']))

    def test_r03_original_bootstrap_local_config_requires_parent_attach(self):
        self.public_spec()
        result = self.invoke_public()
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['nativeThreadId'], self.thread)
        self.assertNotEqual(result['nativeThreadId'], self.parentthread)
        self.assertEqual(result['parentRuntimePid'], self.parent['pid'])
        self.assertEqual(result['nativeIdentity'], self.native)
        self.assertTrue(result['sessionAttachmentRequired'])
        self.assertTrue(result['canonicalObservationRequired'])
        self.assertEqual(self.pin(Path(result['sessionConfigPath']))['sha256'], result['sessionConfigSha256'])
        c = json.loads(Path(result['sessionConfigPath']).read_text())
        self.assertEqual(c, {**self.config, 'nativeThreadId': self.thread})
        self.assertNotIn('SYNTHETIC_CHILD_TOKEN', json.dumps(result))
        self.assertEqual(self.invoke_public(inspect=True), result)
        self.assertEqual(self.rpc_calls.count('thread/start'), 1)
        self.assertEqual(self.rpc_calls.count('thread/settings/update'), 1)
        self.assertNotIn('turn/start', self.rpc_calls)

    def test_r03_unknown_thread_start_is_preserved_not_replayed(self):
        self.public_spec()
        self.thread_lost = True
        self.assertEqual(self.invoke_public()['state'], 'unknown')
        context = self.home / 'state/native-context.json'
        raw = context.read_bytes()
        self.thread_lost = False
        result = self.invoke_public(inspect=True)
        self.assertEqual(result['state'], 'unknown')
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))
        self.assertEqual(context.read_bytes(), raw)
        self.assertEqual(self.rpc_calls.count('thread/start'), 1)
        self.assertFalse((self.home / 'session-config.private.json').exists())

    def test_r03_proven_unstarted_transport_resumes_same_operation_once(self):
        self.public_spec()
        self.transport_fail = True
        self.assertEqual(self.invoke_public()['state'], 'unknown')
        context = self.home / 'state/native-context.json'
        raw = context.read_bytes()
        self.assertFalse(json.loads(raw)['threadStartAttempted'])
        self.transport_fail = False
        self.assertEqual(self.invoke_public(inspect=True)['state'], 'ready')
        prior = self.b / 'operation' / ('unstarted-before-' + f.digest(raw) + '.json')
        self.assertEqual(prior.read_bytes(), raw)
        self.assertEqual(self.rpc_calls.count('thread/start'), 1)
        self.assertEqual(self.rpc_calls.count('initialize'), 2)

    def test_r03_guide_drift_blocks_original_without_native_retry(self):
        self.public_spec()
        self.transport_fail = True
        self.assertEqual(self.invoke_public()['state'], 'unknown')
        original = (self.home / 'state/native-context.json').read_bytes()
        (self.b / 'OPERATIONS.txt').write_text('Different unreviewed guide')
        self.transport_fail = False
        self.assertEqual(self.invoke_public(inspect=True)['state'], 'unknown')
        self.assertEqual((self.home / 'state/native-context.json').read_bytes(), original)
        self.assertEqual(self.rpc_calls.count('initialize'), 1)
        self.assertEqual(self.rpc_calls.count('thread/start'), 0)

    def test_r03_external_process_cannot_bootstrap_logical_session(self):
        self.public_spec()
        with patch.object(f.os, 'getpid', return_value=202):
            self.assertEqual(self.invoke_public()['state'], 'blocked')
        self.assertEqual(self.rpc_calls, [])
        self.assertFalse(self.home.exists())

    def test_r03_static_account_policy_accepts_fresh_parent_incarnation_evidence(self):
        spec = self.public_spec()
        self.policy.pop('parentProcess')
        self.policy.pop('nativeProcess')
        self.put(self.policyfile, self.policy)
        original_policy = self.policyfile.read_bytes()
        spec['parentRuntime']['roomOriginPolicy'] = self.pin(self.policyfile)
        renewed = {**self.parent, 'pid': 202, 'birth': 'accepted-new-parent-incarnation'}
        self.processes[202] = renewed
        spec['parentRuntime']['identity'] = renewed
        self.put(self.publicfile, spec)
        with patch.object(f.os, 'getpid', return_value=202):
            result = self.invoke_public()
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['parentRuntimePid'], 202)
        self.assertEqual(self.policyfile.read_bytes(), original_policy)

    def test_r03_missing_resume_role_guide_is_blocked_before_files(self):
        spec = self.public_spec()
        spec['connectorConfig']['conversationResumeInstructions'] = {}
        self.put(self.publicfile, spec)
        self.assertEqual(self.invoke_public()['state'], 'blocked')
        self.assertEqual(self.rpc_calls, [])
        self.assertFalse(self.home.exists())


if __name__ == '__main__':
    unittest.main()
