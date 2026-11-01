"""Original factory workflow across SDK changes; HTTP credentials are synthetic.

The agent-authentication GET uses a real owned loopback server. Installer/inspect
process results are intercepted, so no host installation or model work occurs.
"""
import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from aiohttp import web

from lax_connector import room_host_provision as factory
from lax_connector.room_administration import RoomAdministration, AdministrationUnconfirmed
from lax_connector.journal import saved


class FactoryReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'), prefix='lax-factory-reconcile-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.authority, self.owner, self.agent, self.host, self.room = [str(uuid4()) for _ in range(5)]
        self.principal = {'id': self.agent, 'authority': self.authority, 'active': True, 'kind': 'agent', 'name': 'Synthetic QA'}
        self.auth_reads = 0
        async def authenticate(request):
            self.assertEqual(request.headers['Authorization'], 'Bearer SYNTHETIC-NOT-A-CREDENTIAL')
            self.auth_reads += 1
            return web.json_response(self.principal)
        app = web.Application(); app.router.add_get('/hollywood/v3/principals/'+self.agent, authenticate)
        self.runner = web.AppRunner(app, access_log=None); await self.runner.setup()
        self.addAsyncCleanup(self.runner.cleanup)
        site = web.TCPSite(self.runner, '127.0.0.1', 0); await site.start()
        self.config = {'authorityId': self.authority, 'agentId': self.owner, 'hostId': self.host,
                       'binary': '/synthetic/old/native', 'codexHome': '/synthetic/original-profile',
                       'model': 'synthetic-no-provider', 'effort': 'low',
                       'provisionInterpreter': '/synthetic/sdk234/python',
                       'hollywoodUrl': 'http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])}
        self.args = {'agentId': self.agent, 'roomId': self.room}
        self.enterContext(patch.object(factory, 'administrator_available', return_value=True))
        saved(self.root/('agent-credential-'+self.agent+'.json'),
              {'authorityId': self.authority, 'agentId': self.agent, 'token': 'SYNTHETIC-NOT-A-CREDENTIAL'})
        self.commands = []
        self.inspect_ready = False
        self.bad_pin = False
        async def spawn(*command, **options):
            self.commands.append(command)
            async def communicate():
                if '--inspect' not in command or not self.inspect_ready:
                    return b'', b'SYNTHETIC readback not yet conclusive'
                pin = {'schema': 'lax-factory-inspection-runtime/v1', 'ownerAgentId': self.owner,
                       'authorityId': self.authority, 'hostId': self.host, 'interpreter': command[2],
                       'originalSpecSha256': command[-1], 'acceptedReleaseOperation': 'a'*64,
                       'acceptedReleaseDigest': 'b'*64}
                if self.bad_pin:pin['ownerAgentId'] = str(uuid4())
                result = {'authorityId': self.authority, 'agentId': self.agent,
                          'inspection': {'setupRepeated': False, 'executionRegistration': {'ready': True}},
                          'maintenanceRuntime': pin}
                return json.dumps(result).encode(), b''
            return SimpleNamespace(returncode=0 if '--inspect' in command and self.inspect_ready else 1,
                                   communicate=communicate)
        self.enterContext(patch.object(asyncio, 'create_subprocess_exec', side_effect=spawn))
        self.enterContext(patch.object(factory, 'sys', SimpleNamespace(executable='/synthetic/sdk236/python')))

    async def request(self, method, path, body=None):
        self.assertEqual(method, 'GET')
        if path == 'principals/'+self.owner:
            return {'id': self.owner, 'authority': self.authority, 'active': True, 'kind': 'agent', 'administrator': True}
        if path == 'principals/'+self.agent:return self.principal
        if path == 'agents/'+self.agent+'/role':
            return {'principal': self.agent, 'authority': self.authority, 'purpose': 'Finite synthetic proof'}
        if path == 'rooms/'+self.room:
            return {'authorityId': self.authority, 'room': {'id': self.room}, 'actors': [{'id': self.agent, 'can_read': True}]}
        self.fail('Unexpected transport call: '+path)

    def administrator(self):
        return RoomAdministration(authority=self.authority, agent=self.owner, thread='original-thread',
                                  request=self.request, state=self.root, host_config=self.config)

    async def start_held(self):
        with self.assertRaises(AdministrationUnconfirmed):
            await self.administrator().call('lax_provision_room_agent', self.args, 'original-call')
        record = json.loads(next(self.root.glob('workflow-*.json')).read_text())
        self.operation = record['operationId']
        self.directory = self.root/('host-'+self.operation.removeprefix('native-admin:'))
        self.file = self.directory/'spec.private.json'
        self.original = self.file.read_bytes()

    async def test_changed_sdk_finishes_original_via_inspection_without_install_replay(self):
        await self.start_held()
        self.assertEqual(len(self.commands), 2)
        old = json.loads(self.original)
        initial = (self.directory/'initial-result.json').read_bytes()
        saved(self.directory/'inspect-result.json', {'returncode': 1, 'stderr': 'retained legacy SDK result'})
        legacy = (self.directory/'inspect-result.json').read_bytes()
        self.config.update(binary='/synthetic/new/native', provisionInterpreter='/synthetic/sdk237/python')
        self.principal['name'] = 'Renamed existing QA'
        with patch.object(factory, 'sys', SimpleNamespace(executable='/synthetic/sdk237/python')):
            self.inspect_ready = True
            result = await self.administrator().call('hollywood_admin_reconcile', {'operationId': self.operation}, 'resume')
        self.assertEqual(result['operationId'], self.operation)
        self.assertTrue(result['executionReady'])
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertEqual((self.directory/'initial-result.json').read_bytes(), initial)
        self.assertEqual((self.directory/'inspect-result.json').read_bytes(), legacy)
        self.assertEqual(old['interpreter'], '/synthetic/sdk234/python')
        self.assertEqual([c for c in self.commands if '--inspect' not in c], [self.commands[0]])
        self.assertEqual([c[2] for c in self.commands], ['/synthetic/sdk234/python', '/synthetic/sdk236/python', '/synthetic/sdk237/python'])
        self.assertTrue(all(c[-1] == hashlib.sha256(self.original).hexdigest() for c in self.commands[1:]))
        self.assertEqual(len(list(self.directory.glob('inspection-runtime-*.json'))), 2)
        first_inspection = [p.read_bytes() for p in self.directory.glob('inspection-*.json') if p.name != 'inspect-result.json']
        # Lost workflow completion after accepted dispatch still reuses that
        # original acceptance, not another installer or inspection.
        workflow = next(self.root.glob('workflow-*.json'))
        record = json.loads(workflow.read_text()); record['state'] = 'unconfirmed'
        saved(workflow, record)
        dispatch = (self.directory/'dispatch.json').read_bytes()
        again = await self.administrator().call('hollywood_admin_reconcile', {'operationId': self.operation}, 'again')
        self.assertEqual(again, result); self.assertEqual(len(self.commands), 3)
        self.assertEqual((self.directory/'dispatch.json').read_bytes(), dispatch)
        self.assertEqual(first_inspection, [p.read_bytes() for p in self.directory.glob('inspection-*.json') if p.name != 'inspect-result.json'])

    async def test_unknown_or_unreviewed_inspection_keeps_original_no_second_installer(self):
        await self.start_held()
        self.inspect_ready = True; self.bad_pin = True
        with self.assertRaises(AdministrationUnconfirmed):
            await self.administrator().call('hollywood_admin_reconcile', {'operationId': self.operation}, 'unreviewed')
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertEqual(sum('--inspect' not in c for c in self.commands), 1)
        self.assertEqual(json.loads((self.directory/'dispatch.json').read_text())['state'], 'dispatching')
        self.file.unlink()
        (self.directory/'dispatch.json').unlink()  # Other original dispatch evidence must still prevent replacement.
        with self.assertRaises(AdministrationUnconfirmed):
            await self.administrator().call('hollywood_admin_reconcile', {'operationId': self.operation}, 'lost-spec')
        self.assertFalse(self.file.exists()); self.assertEqual(len(self.commands), 3)

    async def test_unchanged_legacy_interpreter_keeps_read_only_inspection_contract(self):
        with patch.object(factory, 'sys', SimpleNamespace(executable=self.config['provisionInterpreter'])):
            await self.start_held()
        self.assertEqual(len(self.commands), 2)
        self.assertEqual(self.commands[0][2], self.commands[1][2])
        self.assertEqual(self.commands[1][-1], '--inspect')
        self.assertNotIn('--inspection-owner', self.commands[1])
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertEqual(sum('--inspect' not in c for c in self.commands), 1)


if __name__ == '__main__':
    unittest.main()
