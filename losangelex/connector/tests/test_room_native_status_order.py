"""Native receipt/notification order through real SQLite and room projection.

Only native transport and HTTP are absent; no model or worker is started.
"""
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import tempfile
import unittest
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.conversation_io import ConversationIO
from lax_connector.room_native_state import RoomNativeState

class NativeStatusOrder(unittest.IsolatedAsyncioTestCase):
    async def test_original_source_is_preserved_in_every_ack_start_order(self):
        for order in [('ack','status','start'),('status','ack','start'),('status','start','ack')]:
            with self.subTest(order=order),tempfile.TemporaryDirectory() as name:
                root=Path(name)
                authority,agent,peer,room,other,event_id=[str(uuid4()) for _ in range(6)]
                event={'id':event_id,'authority':authority,'room':room,'kind':'message',
                    'audience':'direct','author':peer,'recipient':agent,'body':'Synthetic scoped instruction',
                    'data':{'authorKind':'agent','conversationRecipients':[agent]}}
                io=ConversationIO(root/'io.sqlite',authority=authority,agent=agent,thread='native-thread')
                try:
                    io.stage(event)
                    async def no_send(*args):raise AssertionError('No HTTP/model effect allowed')
                    c=ConversationalAgent.__new__(ConversationalAgent)
                    c.state=root;c.thread='native-thread';c.native_active_turn=None
                    c.conversation_io=io;c.output=None;c.turn_sources={};c.turn_input_rooms={}
                    c.activity=SimpleNamespace(record=lambda *args:None)
                    c.native_state=RoomNativeState(state=root/'native',thread=c.thread,agent=agent,
                        authority=authority,send=no_send,rooms=[{'roomId':r,'sharedThreadStatus':True} for r in (room,other)])
                    for item in order:
                        if item=='ack':await c.native_receipt(event,{'turn':{'id':'original-turn'}})
                        elif item=='status':await c.event('thread/status/changed',{'threadId':c.thread,
                            'status':{'type':'active','activeFlags':[]}})
                        else:await c.event('turn/started',{'threadId':c.thread,'turn':{'id':'original-turn'}})
                    self.assertEqual(c.native_state.desired(room),{'sourceEventId':event_id,
                        'status':{'type':'active','activeFlags':[]}})
                    self.assertEqual(c.native_state.desired(other),{'sourceEventId':None,
                        'status':{'type':'activeElsewhere','activeFlags':[]}})
                    self.assertEqual(io.db.execute('SELECT event,turn FROM input_source').fetchall()[0]['event'],event_id)
                finally:io.close()

if __name__=='__main__':unittest.main()
