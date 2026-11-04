"""Derived-review identity and unknown-ACK invariants; no semantic simulator."""
import tempfile,unittest
from pathlib import Path
from uuid import uuid4
from lax_connector.conversation_io import ConversationIO
from lax_connector.room_reply_window import ReplyWindow
from lax_connector.errors import HttpFailure

class ReviewJournal(unittest.IsolatedAsyncioTestCase):
    async def test_application_review_preserves_human_receipt_and_lost_ack_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            authority,agent,human,room,event=[str(uuid4()) for _ in range(5)]
            io=ConversationIO(Path(d)/'io.sqlite',authority=authority,agent=agent,thread='original-thread')
            source={'id':event,'seq':4,'authority':authority,'author':human,'room':room,
                'audience':'room','kind':'message','data':{'authorKind':'human','conversationRecipients':[agent]}}
            io.stage(source);io.bind(source,{'turn':{'id':'original-human-turn'}})
            calls=[]
            class Native:
                async def call(self,method,payload):
                    calls.append((method,payload));return {'turn':{'id':'review-turn'}}
            window=ReplyWindow(io,Native());io.reply_window=window
            row={'item':'answer-draft','body':'A redundant answer','turn':'original-human-turn'}
            snapshot={'sourceEventId':event,'observedThrough':5,'peerReplies':[{'id':str(uuid4()),'bodyPreview':'An answer'}]}
            self.assertTrue(await window.review(row,source,snapshot))
            self.assertTrue(await window.review(row,source,snapshot))
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][1]['input'],[])
            self.assertNotIn('clientUserMessageId',calls[0][1])
            self.assertEqual(io.source('original-human-turn'),source)
            self.assertEqual(io.source('review-turn'),source)
            self.assertTrue(window.private_final('review-turn',source))
            # New real human input sharing a native turn remains independently
            # reply eligible; an internal review cannot suppress that answer.
            fresh={**source,'id':str(uuid4()),'seq':6}
            io.stage(fresh);io.bind(fresh,{'turn':{'id':'review-turn'}})
            self.assertEqual(io.source('review-turn'),fresh)
            self.assertFalse(window.private_final('review-turn',fresh))
            class LostAck:
                async def call(self,method,payload):
                    calls.append((method,payload));raise ConnectionError('ACK unknown')
            window.rpc=LostAck()
            unknown={**row,'item':'unknown-review'}
            with self.assertRaises(ConnectionError):await window.review(unknown,source,snapshot)
            with self.assertRaises(HttpFailure) as failure:await window.review(unknown,source,snapshot)
            self.assertEqual(failure.exception.code,'REPLY_REVIEW_UNCONFIRMED')
            self.assertEqual(len(calls),2)
            io.close()
