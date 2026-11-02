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
            event=dict(id=str(uuid4()),authority=authority,room=room,author=human,recipient=agent,
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

    async def test_passive_context_cannot_hide_owed_reply_and_legacy_repair_is_once_only(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as root:
            authority,agent,peer,room,other,human=[str(uuid4()) for _ in range(6)]
            binding=dict(authority=authority,agent=agent,thread='original-thread')
            path=Path(root)/'io.sqlite'
            io=ConversationIO(path,**binding)
            original=dict(id=str(uuid4()),authority=authority,room=room,author=peer,
                audience='room',kind='request',data={'authorKind':'agent','expectsReply':True,'conversationRecipients':[agent]})
            passive={**original,'id':str(uuid4()),'kind':'message',
                'data':{'authorKind':'agent','expectsReply':False,'conversationRecipients':[agent]}}
            for e in (original,passive):io.stage(e);io.bind(e,{'turn':{'id':'original-turn'}})
            self.assertEqual(io.source('original-turn')['id'],original['id'])
            io.final('original-turn','legacy-item','Already completed original work.')
            io.ended('original-turn','completed')
            io.finish('legacy-item','suppressed','Peer publication remains explicit')
            io.close()
            # Exact old schema: canonical inputs/final are retained; the new
            # reply eligibility index did not exist when suppression happened.
            old=sqlite3.connect(path)
            old.execute('DROP INDEX input_reply_turn')
            old.execute('DROP INDEX input_source_unclassified')
            old.execute('ALTER TABLE input_source DROP COLUMN reply_eligible')
            old.execute('DROP TABLE delivery_repair');old.commit();old.close()
            io=ConversationIO(path,**binding)
            self.assertEqual(io.pending(),[])  # No broad historical replay on startup.
            with self.assertRaises(ValueError):io.recover_passive_suppression('legacy-item',passive['id'])
            repaired=io.recover_passive_suppression('legacy-item',original['id'])
            self.assertFalse(repaired['reconciled'])
            self.assertEqual(io.pending()[0]['item'],'legacy-item')
            repair=dict(io.db.execute('SELECT * FROM delivery_repair').fetchone())
            self.assertEqual(repair['source'],original['id'])
            self.assertEqual(repair['previous_reason'],'Peer publication remains explicit')
            posts=[]
            async def request(method,url,payload=None):
                self.assertEqual(method,'POST');posts.append(payload)
                return {'accepted':True,'deliveries':[],'event':dict(authority=authority,
                    author=agent,room=room,kind='message',body=payload['body'],audience='room',
                    source=payload['sourceEventId'],data={'responsePhase':payload['responsePhase']})}
            tools=RoomTools(authority_id=authority,agent_id=agent,thread_id='original-thread',
                request=request,state=Path(root)/'publications',conversation_io=io)
            output=RoomOutput(io,tools)
            await output.deliver(io.pending()[0])
            self.assertEqual(len(posts),1);self.assertEqual(posts[0]['sourceEventId'],original['id'])
            # Ordinary peer chatter still cannot cause automatic reply loops.
            io.stage(passive);io.bind(passive,{'turn':{'id':'original-turn'}})
            only={**passive,'id':str(uuid4())}
            io.stage(only);io.bind(only,{'turn':{'id':'peer-only'}})
            io.final('peer-only','peer-final','Do not broadcast this.');io.ended('peer-only','completed')
            await output.deliver(io.pending()[0]);self.assertEqual(len(posts),1)
            # Passive private context cannot redirect an owed public answer.
            private={**passive,'id':str(uuid4()),'room':other,'audience':'direct','author':human}
            io.stage(private);io.bind(private,{'turn':{'id':'original-turn'}})
            self.assertEqual(io.source('original-turn')['id'],original['id'])
            # Two genuine requests with different audiences remain ambiguous.
            for e in (dict(original,id=str(uuid4())),dict(original,id=str(uuid4()),room=other)):
                io.stage(e);io.bind(e,{'turn':{'id':'ambiguous-turn'}})
            self.assertIsNone(io.source('ambiguous-turn'))
            io.close();io=ConversationIO(path,**binding)
            self.assertEqual(io.pending(),[])
            self.assertEqual(io.db.execute('SELECT count(*) FROM delivery_repair').fetchone()[0],1)
            self.assertEqual(io.recover_passive_suppression('legacy-item',original['id'])['state'],'accepted')
            with self.assertRaises(ValueError):io.recover_passive_suppression('peer-final',only['id'])
            self.assertEqual(io.pending(),[])
            self.assertEqual(len(posts),1);io.close()

            # The real maintenance CLI must fail before touching a live owner.
            import subprocess,sys
            from lax_connector.runtime_files import exclusive_lock
            state=Path(root)/"cli-state";state.mkdir(mode=0o700)
            cli=ConversationIO(state/"conversation-io.sqlite",**binding)
            for e in (original,passive):cli.stage(e);cli.bind(e,{"turn":{"id":"cli-turn"}})
            cli.final("cli-turn","cli-final","Preserved CLI result");cli.ended("cli-turn","completed")
            cli.finish("cli-final","suppressed","Peer publication remains explicit");cli.close()
            config=state/"connector.json";config.write_text(json.dumps({"state":str(state),"authorityId":authority,"agentId":agent,"nativeThreadId":"original-thread"}));config.chmod(0o600)
            lock=state/"connector.lock";lock.touch(mode=0o600)
            args=[sys.executable,"-m","lax_connector.repair_room_output","--config",str(config),"--item","cli-final","--source-event",original["id"]]
            with lock.open("r+") as held:
                exclusive_lock(held)
                denied=subprocess.run(args,capture_output=True,text=True,timeout=5)
                self.assertNotEqual(denied.returncode,0)
                db=sqlite3.connect(state/"conversation-io.sqlite");self.assertEqual(db.execute("SELECT state FROM output").fetchone()[0],"suppressed");db.close()
            done=subprocess.run(args,capture_output=True,text=True,timeout=5);self.assertEqual(done.returncode,0,done.stderr)
            self.assertFalse(json.loads(done.stdout)["reconciled"])
            again=subprocess.run(args,capture_output=True,text=True,timeout=5);self.assertEqual(again.returncode,0,again.stderr)
            self.assertTrue(json.loads(again.stdout)["reconciled"])
