"""Replay an actual delayed command event through native notification transport.
No model calls or business/API mutations; model qualification remains separate.
"""
import asyncio,copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from lax_connector.context_runtime import ContextRunner
from lax_connector.execution_scope import ExecutionScope

FIXTURE=Path(__file__).parent/'fixtures'/'late_command_completion_r208.json'

class LateActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.case=json.loads(FIXTURE.read_text())
        old=self.case['originalAdmission']['executionScopes'][0]
        config={'agentId':old['agentId'],'authorityId':old['authorityId'],
            'hostId':old['hostId'],'workspaceId':old['workspaceId'],
            'contextIds':{'writer':old['contextId']},
            'binary':'/unused','state':str(self.root),
            'homes':{p:str(self.root/p) for p in ('reader','writer','responder')},
            'tokens':{p:'mechanical-fixture-only' for p in ('reader','writer','responder')}}
        agent=SimpleNamespace(config=config,state=self.root,stop=asyncio.Event())
        self.runner=ContextRunner(agent,'writer')
        self.runner.thread=old['nativeThread']
        newer=self.case['continuedAdmission']['executionScopes'][0]
        self.runner.turn=newer['nativeTurn']
        self.runner.active=True
        self.runner.finished=asyncio.get_running_loop().create_future()
        self.runner.execution_scope=ExecutionScope.accepted(
            self.case['continuedAdmission'],agent=old['agentId'],
            thread=old['nativeThread'],turn=newer['nativeTurn'],
            materials=[newer['materialId']])
        self.original_path=self.runner.state/('execution-'+old['nativeTurn']+'.json')
        self.original_path.write_text(json.dumps(self.case['originalAdmission']))
        self.message=copy.deepcopy(self.case['notification'])
        self.rpc=self.runner.rpc
        self.stream=asyncio.StreamReader()
        self.rpc.process=SimpleNamespace(stdout=self.stream)
        self.reply=asyncio.get_running_loop().create_future()
        self.rpc.pending[37]=self.reply
        self.readtask=None

    async def asyncTearDown(self):
        if self.readtask:
            self.stream.feed_eof()
            await asyncio.gather(self.readtask,return_exceptions=True)
        if self.runner.finished.done() and not self.runner.finished.cancelled():
            self.runner.finished.exception()

    async def replay(self):
        self.readtask=asyncio.create_task(self.rpc._read())
        self.stream.feed_data((json.dumps(self.message)+'\n'+json.dumps({'id':37,'result':{'alive':True}})+'\n').encode())
        response=await asyncio.wait_for(asyncio.shield(self.reply),1)
        self.assertEqual(response,{'alive':True})
        self.assertFalse(self.runner.agent.stop.is_set())
        self.assertFalse(self.runner.finished.done())

    async def test_old_command_completion_keeps_original_scope_and_connection(self):
        await self.replay()
        rows=[json.loads(p.read_text()) for p in self.runner.state.glob('activity-*.json') if len(p.stem)==73]
        self.assertEqual(len(rows),1)
        original=self.case['originalAdmission']['executionScopes'][0]
        self.assertEqual(rows[0]['executionScope'],original)
        self.assertEqual(rows[0]['payload']['nativeTurn'],original['nativeTurn'])
        self.assertNotEqual(rows[0]['payload']['nativeTurn'],self.runner.turn)

    async def test_known_late_completion_is_observed_while_agent_idle(self):
        self.runner.active=False
        self.runner.execution_scope=None
        await self.replay()
        rows=[json.loads(p.read_text()) for p in self.runner.state.glob('activity-*.json') if len(p.stem)==73]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['payload']['nativeTurn'],self.message['params']['turnId'])

    async def test_unbound_turn_is_retained_as_gap_without_relabelling_or_disconnect(self):
        self.message['params']['turnId']=str(uuid4())
        await self.replay()
        self.assertEqual(list(self.runner.state.glob('activity-'+'[0-9a-f]'*64+'.json')),[])
        gaps=list((self.runner.state/'activity-gaps').glob('*.json'))
        self.assertEqual(len(gaps),1)
        self.assertEqual(json.loads(gaps[0].read_text())['notification'],self.message)

    async def test_other_context_receipt_grants_no_activity_attribution(self):
        changed=copy.deepcopy(self.case['originalAdmission'])
        changed['executionScopes'][0]['contextId']=str(uuid4())
        self.original_path.write_text(json.dumps(changed))
        await self.replay()
        self.assertEqual(list(self.runner.state.glob('activity-'+'[0-9a-f]'*64+'.json')),[])
        self.assertEqual(len(list((self.runner.state/'activity-gaps').glob('*.json'))),1)

if __name__=='__main__':unittest.main()
