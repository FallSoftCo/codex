import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from lax_connector.room_origin_factory import origin_configuration
from lax_connector.room_participation import resume_overrides
from lax_connector.room_tools import RoomTools,TOOLS
from lax_connector.room_origin_control import RoomOriginControl
from lax_connector import room_bootstrap

class OriginTests(unittest.IsolatedAsyncioTestCase):
 async def test_actual_cold_bootstrap_and_resume_contract_do_not_inherit_global(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);workspace=root/'new-work';workspace.mkdir();home=root/'profile';home.mkdir()
   old={'runtimeMode':'room-conversation','authorityId':str(uuid4()),'agentId':str(uuid4()),'hostId':str(uuid4()),'binary':'/original/binary','codexHome':str(home),'model':'original-model','effort':'high','sandbox':'danger-full-access','approvalPolicy':'never','hollywoodUrl':'http://127.0.0.1:1','nativeServer':{'manifest':'/original/manifest'},'instructions':'You are Global ultimate enterprise coordinator','conversationResumeInstructions':{'baseInstructions':'You are Global ultimate enterprise coordinator','developerInstructions':'OLD GLOBAL CONTRACT'},'nativeThreadId':'OLD-GLOBAL-THREAD','conversationInstructionAdoption':{'bad':'old'},'conversationDynamicTools':['OLD TOOLS'],'rooms':[{'roomId':str(uuid4()),'after':500}],'state':'OLDSTATE','workspace':'OLDWORK'}
   before=json.dumps(old,sort_keys=True);agent,room=str(uuid4()),str(uuid4())
   config=origin_configuration(old,agent=agent,name='8bar CPU local contributor',room=room,credential='private-fixture',state=root/'new-state',workspace=workspace,operating_instructions=[{'path':'/approved/AGENTS.md','sha256':'a'*64}])
   self.assertEqual(json.dumps(old,sort_keys=True),before)
   self.assertEqual(config['rooms'],[{'roomId':room,'after':0}]);self.assertNotIn('nativeThreadId',config);self.assertNotIn('conversationInstructionAdoption',config)
   overrides,adoption=resume_overrides(config);self.assertIsNone(adoption);self.assertEqual(overrides['baseInstructions'],config['instructions']);self.assertNotIn('OLD GLOBAL CONTRACT',json.dumps(config));self.assertNotIn('You are Global',config['instructions']);self.assertEqual(config['conversationDynamicTools'],TOOLS);self.assertIn('/approved/AGENTS.md',config['instructions']);self.assertEqual(config['hostOperatingInstructions'][0]['sha256'],'a'*64)
   calls=[]
   class Rpc:
    async def start(self):calls.append(('connect-existing',None))
    async def close(self):calls.append(('disconnect-only',None))
    async def call(self,method,args):
     calls.append((method,args))
     if method=='thread/start':return {'thread':{'id':'NEW-DISTINCT-EMPTY-THREAD'},'sandbox':{'type':'dangerFullAccess'},'approvalPolicy':'never'}
     return {}
   with patch.object(room_bootstrap,'native_client',return_value=Rpc()),patch.object(room_bootstrap,'host_manifest',return_value={'state':str(root/'existing-native-state')}):
    first=await room_bootstrap.initialize(config);second=await room_bootstrap.initialize(config)
   self.assertEqual(first,second);self.assertEqual(first['modelTurnsRequested'],0);self.assertEqual(first['nativeThreadId'],'NEW-DISTINCT-EMPTY-THREAD')
   self.assertEqual(sum(m=='thread/start' for m,_ in calls),1);self.assertFalse(any(m.startswith('turn/') for m,_ in calls));request=next(a for m,a in calls if m=='thread/start');self.assertEqual(request['baseInstructions'],overrides['baseInstructions']);self.assertNotIn('Global ultimate',request['baseInstructions'])

 async def test_new_semantic_coordination_does_not_inherit_private_reply_but_guards_remain(self):
  with tempfile.TemporaryDirectory() as d:
   authority,agent,room,other,root,source=[str(uuid4()) for _ in range(6)];writes=[]
   original={'id':source,'room':room,'audience':'direct','author':root,'recipient':agent}
   class IO:
    def source(self,*_):return original
    def input_event(self,_):return original
    def observe_own_reply(self,_):return False
   async def request(method,path,body=None):
    self.assertEqual(method,'POST');writes.append(body)
    return {'accepted':True,'event':{'id':str(uuid4()),'authority':authority,'author':agent,'room':room,'kind':'message','body':body['body'],'audience':body['audience'],'recipient':body.get('recipientId'),'source':body.get('sourceEventId'),'data':{'responsePhase':body['responsePhase']}},'deliveries':[]}
   tools=RoomTools(authority_id=authority,agent_id=agent,thread_id='existing',request=request,state=Path(d)/'tools',conversation_io=IO())
   args={'body':'New public-code contract to peer, not copied private source','audience':'direct','recipientId':other,'responsePhase':'message'}
   with self.assertRaisesRegex(ValueError,'Private source'):await tools.publish(room,args,'old-default',turn='turn')
   self.assertEqual(writes,[])
   await tools.publish(room,{**args,'sourceEventId':None},'new-semantic',turn='turn');self.assertEqual(len(writes),1);self.assertNotIn('sourceEventId',writes[0])
   with self.assertRaisesRegex(ValueError,'only new semantic'):await tools.publish(room,{**args,'sourceEventId':None,'responsePhase':'answer'},'no-answer-bypass',turn='turn')
   with self.assertRaisesRegex(ValueError,'Private source'):await tools.publish(room,{**args,'sourceEventId':source,'audience':'room'},'no-private-expansion',turn='turn')
   self.assertEqual(len(writes),1)

 async def test_metadata_control_starts_once_without_model_and_unknown_does_not_block_other_room(self):
  with tempfile.TemporaryDirectory() as d:
   authority,agent,node=[str(uuid4()) for _ in range(3)];rooms=[str(uuid4()),str(uuid4())];calls=[]
   config={'authorityId':authority,'agentId':agent,'hostId':node,'state':str(Path(d)/'parent')};slots=[{'room':r,'node':node,'agent':str(uuid4()),'state':'pending','revision':1,'receipt':None} for r in rooms]
   async def call(owner,name,args,call_id):
    calls.append(args['roomId'])
    if args['roomId']==rooms[0]:raise RuntimeError('Original unknown installer receipt held')
    return {'complete':False,'meaning':'Waiting actual native observation'}
   with patch('lax_connector.room_origin_control.RoomAdministration.call',call):
    control=RoomOriginControl(config=config,request=None,thread='unchanged-global',state=Path(d)/'control')
    value={'authorityId':authority,'roomAgentInitializations':slots};control.observe(value);control.observe(value)
    await asyncio.gather(*list(control.active.values()));self.assertCountEqual(calls,rooms)
    control.observe(value);self.assertEqual(len(calls),2)
    restarted=RoomOriginControl(config=config,request=None,thread='unchanged-global',state=Path(d)/'control');restarted.observe(value);self.assertEqual(len(restarted.active),0)
    await control.close();await restarted.close()
