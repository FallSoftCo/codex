"""Filesystem/initialization invariants; no native/model/service claims."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from lax_connector.journal import saved
from lax_connector.project_adoption import reviewed_configuration,role_receipt,RoleHandoverPending,accepts_initialization
from lax_connector.room_session_supervisor import RoomSessionSupervisor

class ProjectAdoptionTest(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.agent=str(uuid4());self.room=str(uuid4());self.authority=str(uuid4());self.host=str(uuid4())
  self.state=self.root/'slots'/self.agent/'state';self.state.mkdir(mode=0o700,parents=True)
  self.work=self.state.parent/'work';self.work.mkdir()
  self.parent=dict(state=str(self.root/'parent'),agentId=str(uuid4()),authorityId=self.authority,hostId=self.host,
      nativeThreadId=str(uuid4()),nativeServer={'manifest':'fixture-no-native-transport'},codexHome='fixture-no-auth',roomOriginPolicy={'path':'fixture-approved-host-boundary','sha256':'f'*64})
  self.old=dict(runtimeMode='room-conversation',agentId=self.agent,authorityId=self.authority,hostId=self.host,
      nativeThreadId=str(uuid4()),originRoomId=self.room,rooms=[{'roomId':self.room,'after':0}],
      state=str(self.state),workspace=str(self.work),nativeServer=self.parent['nativeServer'],codexHome=self.parent['codexHome'],
      instructions='Retain owner privacy constraints.',conversationResumeInstructions={'baseInstructions':'Retain owner privacy constraints.','developerInstructions':'Retain deliberate stops.'},
      model='retained-model',effort='xhigh',sandbox='danger-full-access',approvalPolicy='never')
  self.oldfile=self.root/'session-config.private.json';saved(self.oldfile,self.old);self.oldbytes=self.oldfile.read_bytes()
  self.oldrecord=dict(agentId=self.agent,originRoomId=self.room,nativeThreadId=self.old['nativeThreadId'],sessionConfigPath=str(self.oldfile),sessionConfigSha256=hashlib.sha256(self.oldbytes).hexdigest())
  self.policy=dict(version=1,mode='lead',leadAgentId=self.agent,revision=1,inputAfterSeq=17)
  self.new=reviewed_configuration(self.old,self.policy,self.oldrecord['sessionConfigSha256'])
  self.newfile=self.root/'session-config-project.private.json';saved(self.newfile,self.new)
  self.journal=self.state/'project-adoptions'/'original.json';self.journal.parent.mkdir(mode=0o700)
  self.current={**self.oldrecord,'sessionConfigPath':str(self.newfile),'sessionConfigSha256':hashlib.sha256(self.newfile.read_bytes()).hexdigest(),'roleAdoptionReceipt':str(self.journal)}
  self.held={**self.current,'roleAdoptionIntent':str(self.journal)};self.held.pop('roleAdoptionReceipt')
  self.base=dict(schema='lax-project-role-adoption/v1',originalConfig=self.old,originalRecord=self.oldrecord,
      originalConfigSha256=self.oldrecord['sessionConfigSha256'],policy=self.policy)
  self.creations=[]
  def factory(config):
   self.creations.append(config)
   async def serve():await __import__('asyncio').Event().wait()
   return SimpleNamespace(serve=serve,native_state=SimpleNamespace(status={'type':'idle'}),native_active_turn=None,conversation_io=SimpleNamespace(pending=lambda:[]))
  self.factory=factory
  self.host=patch('lax_connector.room_session_supervisor.host_policy',return_value=({'root':str(self.root/'slots'),'workspaceRelative':'work'},{}));self.host.start();self.addCleanup(self.host.stop)
 def supervisor(self):return RoomSessionSupervisor(SimpleNamespace(config=self.parent,thread=self.parent['nativeThreadId']),session_factory=self.factory)
 def write(self,record):
  p=Path(self.parent['state'])/'room-sessions'/('session-'+self.agent+'.json');p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);saved(p,record)
 def accept(self):saved(self.journal,{**self.base,'state':'accepted','receipt':{'newRecord':self.current}})
 async def test_restart_holds_both_incomplete_pointer_forms_then_reuses_original_initialization(self):
  saved(self.journal,{**self.base,'state':'prepared'});self.write(self.held)
  first=self.supervisor();first.load();self.assertEqual(self.creations,[])
  self.assertEqual(first.records[self.agent]['errorType'],'RoleHandoverPending')
  self.write(self.current)
  second=self.supervisor();second.load();self.assertEqual(self.creations,[])
  self.accept();third=self.supervisor();third.load();self.assertEqual(self.creations,[self.new]);self.assertNotEqual(third.records[self.agent].get('state'),'blocked')
  try:
   self.assertTrue(accepts_initialization(self.oldrecord,self.current))
   third.attach({**self.oldrecord,'state':'ready','sharedAppServer':True})
   self.assertEqual(self.creations,[self.new]);self.assertEqual(self.oldfile.read_bytes(),self.oldbytes)
  finally:await third.close()
 async def test_accepted_role_does_not_regenerate_from_later_sdk_templates(self):
  self.accept()
  with patch('lax_connector.project_adoption.reviewed_configuration',side_effect=AssertionError('Later templates must not reapprove a retained role')):
   self.assertEqual(role_receipt(self.current)['state'],'accepted')
   self.assertTrue(accepts_initialization(self.oldrecord,self.current))
 async def test_changed_successor_cannot_load_even_with_an_accepted_journal(self):
  self.accept();saved(self.newfile,{**self.new,'model':'unreviewed-model'});self.write(self.current)
  supervisor=self.supervisor();supervisor.load();self.assertEqual(self.creations,[])
  with self.assertRaises(ValueError):role_receipt(self.current)
  self.assertEqual(self.oldfile.read_bytes(),self.oldbytes)

if __name__=='__main__':unittest.main()
