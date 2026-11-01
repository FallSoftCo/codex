"""Native receipt/output integration, including lost HTTP acceptance and reopen."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from lax_connector.conversation_io import ConversationIO
from lax_connector.room_output import RoomOutput
from lax_connector.room_tools import RoomTools


class OutputIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_causal_receipt_reopen_lost_ack_and_explicit_suppression(self):
        with tempfile.TemporaryDirectory() as root:
            authority,agent,human,room,other = [str(uuid4()) for _ in range(5)]
            binding=dict(authority=authority,agent=agent,thread='original-thread')
            path=Path(root)/'io.sqlite'
            io=ConversationIO(path,**binding)
            event=dict(id=str(uuid4()),authority=authority,room=room,author=human,
                       audience='direct',data={'authorKind':'human','conversationRecipients':[agent]})
            io.stage(event)
            io.final('turn-1','final-1','La risposta è pronta.')
            io.ended('turn-1','completed')
            self.assertIsNone(io.source('turn-1'))
            io.bind(event,{'turn':{'id':'turn-1'}})
            io.close()
            io=ConversationIO(path,**binding)
            accepted={};posts=[];reads=[]
            async def request(method,url,payload=None):
                if method=='GET':
                    reads.append(url)
                    return accepted[url.removeprefix('commands/')]
                posts.append((url,payload))
                result={'accepted':True,'deliveries':[], 'event':dict(
                    id=str(uuid4()),authority=authority,author=agent,room=room,kind='message',
                    body=payload['body'],audience=payload['audience'],recipient=payload.get('recipientId'),
                    source=payload.get('sourceEventId'),data={'responsePhase':payload['responsePhase']})}
                accepted[payload['operationId']]=result
                raise ConnectionError('accepted but response lost')
            tools=RoomTools(authority_id=authority,agent_id=agent,thread_id='original-thread',
                            request=request,state=Path(root)/'publications',conversation_io=io)
            output=RoomOutput(io,tools)
            await output.deliver(io.pending()[0])
            self.assertEqual(len(posts),1)
            self.assertEqual(len(reads),1)
            self.assertEqual(posts[0][1]['recipientId'],human)
            self.assertEqual(posts[0][1]['sourceEventId'],event['id'])
            self.assertEqual(io.pending(),[])
            io.final('turn-1','final-2','A repeated final must not be posted.')
            await output.deliver(io.pending()[0])
            self.assertEqual(len(posts),1)
            # A passive second room cannot replace the original causal scope.
            second={**event,'id':str(uuid4()),'room':other}
            io.stage(second)
            self.assertEqual(io.source('turn-1')['room'],room)
            io.bind(second,{'turn':{'id':'turn-1'}})
            self.assertIsNone(io.source('turn-1'))
            self.assertEqual(io.source('turn-1',room)['id'],event['id'])
            io.close()

    async def test_long_utf8_final_is_preserved_and_peer_final_does_not_wake(self):
        with tempfile.TemporaryDirectory() as root:
            authority,agent,human,room=[str(uuid4()) for _ in range(4)]
            io=ConversationIO(Path(root)/'io.sqlite',authority=authority,agent=agent,thread='t')
            event=dict(id=str(uuid4()),authority=authority,room=room,author=human,
                       audience='room',data={'authorKind':'human','conversationRecipients':[agent]})
            io.stage(event);io.bind(event,{'turn':{'id':'turn'}})
            body='È una risposta. '*1000
            io.final('turn','item',body);io.ended('turn','completed')
            posts=[]
            async def request(method,url,payload=None):
                posts.append(payload)
                return {'accepted':True,'deliveries':[],'event':dict(authority=authority,
                    author=agent,room=room,kind='message',body=payload['body'],audience='room',
                    source=event['id'],data={'responsePhase':payload['responsePhase']})}
            tools=RoomTools(authority_id=authority,agent_id=agent,thread_id='t',request=request,
                            state=Path(root)/'publications',conversation_io=io)
            output=RoomOutput(io,tools)
            await output.deliver(io.pending()[0])
            self.assertEqual(''.join(x['body'] for x in posts),body)
            self.assertTrue(all(len(x['body'].encode())<=6000 for x in posts))
            self.assertEqual(posts[-1]['responsePhase'],'answer')
            peer={**event,'id':str(uuid4()),'data':{'authorKind':'agent','conversationRecipients':[agent]}}
            io.stage(peer);io.bind(peer,{'turn':{'id':'peer-turn'}})
            io.final('peer-turn','peer-final','An automatic peer answer would loop.')
            io.ended('peer-turn','completed')
            before=len(posts);await output.deliver(io.pending()[0]);self.assertEqual(len(posts),before)
            io.close()
