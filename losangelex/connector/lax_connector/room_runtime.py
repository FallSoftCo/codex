"""Event-driven room input for an existing native conversation.

The owner supplies the already-running RPC and its existing thread. This class
never creates a model process, claims work, changes tools or samples on timers.
"""
from .runtime_files import state_directory
import asyncio
import json
import random
from pathlib import Path
from uuid import UUID

from .room_input import human_input, peer_context, peer_request
from .room_receive import RoomReceiveJournal, NativeReceiptUnresolved


class RoomRuntime:
    def __init__(self, *, rpc, session, base_url, token, authority_id, agent_id,
                 room_id, thread_id, state, initial_cursor, on_status=None, route_headers=None, on_room_event=None, before_native_input=None, on_native_receipt=None, project_mode=False, on_input_candidate=None):
        self.rpc, self.session = rpc, session
        self.route_headers=dict(route_headers or {})
        if set(self.route_headers)-{'X-Hollywood-Authority','X-Hollywood-Agent'}:
            raise ValueError('Only explicit federation routing headers accepted')
        self.base_url, self.token = base_url.rstrip('/')+'/', token
        self.authority = str(UUID(authority_id))
        self.agent = str(UUID(agent_id))
        self.room = str(UUID(room_id))
        self.thread = thread_id
        if not thread_id or not isinstance(initial_cursor,int) or isinstance(initial_cursor,bool) or initial_cursor < 0:
            raise ValueError('Existing native thread and explicit receive boundary required')
        self.state = Path(state)
        state_directory(self.state, parents=True,exist_ok=True)
        self.journal = RoomReceiveJournal(self.state/'receive.sqlite')
        # Addressed inputs and human conversation are different filtered feeds.
        # Retain the legacy cursor; it cannot cover messages excluded from it.
        self.cursor_path = self.state/('inputs-cursor.json' if project_mode else 'cursor.json')
        self.binding = {'authority':self.authority,'agent':self.agent,'room':self.room,'thread':thread_id}
        if self.cursor_path.exists():
            saved=json.loads(self.cursor_path.read_text())
            if saved['binding'] != self.binding:
                raise ValueError('Saved room receive binding differs')
            self.cursor=saved['cursor']
        else:
            self.cursor=initial_cursor
            self._save_cursor()
        self.on_room_event=on_room_event
        self.before_native_input=before_native_input
        self.on_native_receipt=on_native_receipt
        self.project_mode=project_mode
        self.on_input_candidate=on_input_candidate
        self.on_status=on_status
        self.ready=asyncio.Event()

    def _save_cursor(self):
        # Input receipts are committed before this replace. Re-reading an event
        # after a cursor-write failure cannot cause another native submission.
        from .journal import saved
        saved(self.cursor_path,{'binding':self.binding,'cursor':self.cursor})

    async def _status(self, state, **details):
        if self.on_status:
            await self.on_status({'state':state,'roomId':self.room,**details})

    async def consume(self,event):
        if event.get('authority')!=self.authority or event.get('room')!=self.room:
            raise ValueError('Room stream crossed its bound scope')
        seq=event.get('seq')
        if not isinstance(seq,int) or isinstance(seq,bool) or seq<0:
            raise ValueError('Canonical sequence required')
        if seq<=self.cursor:return
        if self.on_room_event:await self.on_room_event(event)
        data=event.get('data',{})
        own_wake=(self.project_mode and event.get('author')==self.agent and data.get('coordination',{}).get('type')=='wake' and data.get('leadAgentId')==self.agent)
        if (event.get('author') != self.agent or own_wake) and self.agent in data.get('conversationRecipients',[]):
            args=dict(authority_id=self.authority,agent_id=self.agent,thread_id=self.thread)
            if data.get('authorKind')=='human':
                method,payload='turn/start',human_input(event,**args)
            elif data.get('authorKind')=='agent':
                if self.project_mode and event.get('recipient')!=self.agent:
                    raise ValueError('Project team input must be explicitly addressed')
                payload=peer_context(event,**args)
                method='hollywood/agentMessage' if event.get('recipient')==self.agent else 'thread/inject_items'
            else:
                raise ValueError('Unexpected canonical conversation author')
            row=self.journal.stage(authority=self.authority,agent=self.agent,event=event['id'],thread=self.thread,
                                   seq=seq,payload={'method':method,'params':payload},canonical=event)
            original=json.loads(row['payload'])
            method,payload=original['method'],original['params']
            inference = method != 'thread/inject_items'
            if self.journal.observation(self.authority,self.agent,event['id']):
                self.cursor=seq;self._save_cursor();return
            if row['acknowledgement'] is None:
                if row['state'] != 'received':
                    raise NativeReceiptUnresolved('Original room input needs reconciliation: '+event['id'])
                if inference and self.on_input_candidate:
                    decision=await self.on_input_candidate(event)
                    if decision.get('admit') is False:
                        self.journal.observe_only(self.authority,self.agent,event['id'],decision['reason'])
                        self.cursor=seq;self._save_cursor();return
                if inference and self.before_native_input:await self.before_native_input(event)
                if not self.journal.begin_handoff(self.authority,self.agent,event['id']):
                    raise NativeReceiptUnresolved('Original room input needs reconciliation: '+event['id'])
                if method=='hollywood/agentMessage':
                    reply=await self.rpc.call(method,peer_request(payload,agent_id=self.agent))
                else:
                    reply=await self.rpc.call(method,payload)
                self.journal.acknowledge(self.authority,self.agent,event['id'],reply)
            else:
                reply=json.loads(row['acknowledgement'])
            if inference and self.on_native_receipt:await self.on_native_receipt(event,reply)
        self.cursor=seq
        self._save_cursor()

    async def run(self):
        attempts=0
        while True:
            try:
                url=self.base_url+'rooms/'+self.room+'/events'
                async with self.session.get(url,params={'view':'inputs' if self.project_mode else 'conversation','batch':'1','after':str(self.cursor)},
                        headers={**self.route_headers,'Authorization':'Bearer '+self.token}) as response:
                    if response.status in (401,403):
                        await self._status('blocked',reason='Room access denied',httpStatus=response.status)
                        return
                    response.raise_for_status()
                    self.ready.set()
                    await self._status('connected')
                    attempts=0
                    async for raw in response.content:
                        line=raw.decode().strip()
                        if not line.startswith('data: '):continue
                        packet=json.loads(line[6:])
                        events=packet.get('events',[packet] if 'id' in packet else [])
                        for event in events:await self.consume(event)
            except asyncio.CancelledError:
                raise
            except NativeReceiptUnresolved as error:
                await self._status('needs_reconciliation',reason=str(error))
                return
            except (ValueError,KeyError,TypeError) as error:
                await self._status('blocked',reason='Invalid room stream: '+str(error))
                return
            except Exception as error:
                # Reconnect transport only. Never start another turn to check work.
                attempts+=1
                await self._status('reconnecting',reason=type(error).__name__)
            await asyncio.sleep(min(30,2**min(attempts,5))*random.uniform(.8,1.2))

    def close(self):
        self.journal.close()
