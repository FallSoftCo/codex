import json,unittest
from pathlib import Path
from lax_connector.room_resume import configured_resume,supported_declarations
from lax_connector.room_tools import TOOLS
class Rpc:
 shared=True
 def __init__(self,status,identity='original'):self.status=status;self.identity=identity;self.calls=[];self.bound=[]
 def bind_thread(self,thread):self.bound.append(thread)
 async def call(self,method,params):self.calls.append((method,params));return {'thread':{'id':self.identity,'status':{'type':self.status}}}
class Resume(unittest.IsolatedAsyncioTestCase):
 async def test_warm_keeps_tools_without_history(self):
  r=Rpc('idle');p={'threadId':'original','excludeTurns':True};self.assertEqual(await configured_resume(r,p,TOOLS),p);self.assertEqual(r.calls,[('thread/read',{'threadId':'original','includeTurns':False})]);self.assertEqual(r.bound,['original'])
 async def test_active_reconnect_preserves_tools_and_turn(self):
  r=Rpc('active');self.assertNotIn('dynamicTools',await configured_resume(r,{'threadId':'original'},TOOLS));self.assertEqual(len(r.calls),1)
 async def test_cold_uses_reviewed_tools(self):
  self.assertEqual((await configured_resume(Rpc('notLoaded'),{'threadId':'original'},TOOLS))['dynamicTools'],TOOLS)
 async def test_foreign_or_unknown_holds(self):
  with self.assertRaises(ValueError):await configured_resume(Rpc('idle','foreign'),{'threadId':'original'},TOOLS)
  with self.assertRaises(RuntimeError):await configured_resume(Rpc('unavailable'),{'threadId':'original'},TOOLS)
 def test_previous_exact_schema_supported(self):
  previous=json.loads((Path(__file__).parent/'fixtures/room-tools-sdk244.json').read_text());self.assertTrue(supported_declarations(previous,TOOLS,[]));previous[0]['description']+=' changed';self.assertFalse(supported_declarations(previous,TOOLS,[]))
 def test_arbitrary_or_current_declarations(self):
  self.assertTrue(supported_declarations(TOOLS,TOOLS,[]));self.assertFalse(supported_declarations(None,TOOLS,[]));self.assertFalse(supported_declarations([{'name':'arbitrary'}],TOOLS,[]))
