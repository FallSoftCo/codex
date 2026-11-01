"""Durable native observations, separate from room conversation and model input."""
from .runtime_files import state_directory
import asyncio
import hashlib
import json
import random
from pathlib import Path
from .journal import saved
from .errors import HttpFailure

KINDS={'commandExecution':'Command','fileChange':'File changes','mcpToolCall':'MCP tool',
       'dynamicToolCall':'Native tool','collabAgentToolCall':'Agent operation'}

class RoomActivity:
    def __init__(self,*,state,thread,agent,send):
        self.state=Path(state);state_directory(self.state, parents=True,exist_ok=True)
        self.thread,self.agent,self.send=thread,agent,send
        self.wake=asyncio.Event();self.task=None;self.pending=set()

    def record(self,method,params,source):
        if method not in ('item/started','item/completed') or params.get('threadId')!=self.thread:return
        item=params['item']
        if item.get('type') not in KINDS:return
        turn=params['turnId'];identity=item['id']
        key=hashlib.sha256(json.dumps([self.agent,self.thread,turn,identity]).encode()).hexdigest()
        origin=self.state/(key+'-origin.json')
        if origin.exists():source=json.loads(origin.read_text())['source']
        elif source:
            # Capture before another human steer or peer input changes the turn's
            # current source. Completion always uses this original scope.
            saved(origin,{'source':source})
        else:
            saved(self.state/'observation-gap.json',{'turn':turn,'itemId':identity,'reason':'Native item origin unavailable','executionReplayed':False})
            return
        phase=method.split('/')[1]
        status='inProgress' if phase=='started' else item.get('status','completed')
        if status not in ('inProgress','completed','failed','declined') or phase=='completed' and status=='inProgress':status='unknown'
        digest=hashlib.sha256(json.dumps(item,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        payload={'operationId':'native-activity:'+key+':'+phase,'sourceEventId':source['id'],
                 'nativeThread':self.thread,'nativeTurn':turn,'itemId':identity,'phase':phase,
                 'nativeItemDigest':digest,'item':{'nativeType':item['type'],'title':KINDS[item['type']],'status':status}}
        path=self.state/(key+'-'+phase+'.json')
        if path.exists():
            if json.loads(path.read_text())['payload']!=payload:raise ValueError('Original native action observation changed')
            return
        # Raw tool arguments/output stay private. In particular a room read tool
        # must not republish another room's private content to this source room.
        saved(path,{'state':'pending','room':source['room'],'payload':payload,'nativeItem':item})
        self.pending.add(path);self.wake.set()

    def start(self):
        if self.task is not None:raise RuntimeError('Observation drain already started')
        for path in self.state.glob('*.json'):
            if path.name.endswith('-origin.json') or path.name=='observation-gap.json':continue
            if json.loads(path.read_text())['state']=='pending':self.pending.add(path)
        self.task=asyncio.create_task(self.drain());self.wake.set()

    async def drain(self):
        delay=1
        while True:
            await self.wake.wait();self.wake.clear();pending=False
            for path in tuple(self.pending):
                record=json.loads(path.read_text())
                if record['state']!='pending':continue
                try:
                    receipt=await asyncio.wait_for(self.send('POST','rooms/'+record['room']+'/activity',record['payload']),30)
                    event=receipt.get('event',{});data=event.get('data',{})
                    if (not receipt.get('accepted') or receipt.get('deliveries')!=[]
                            or event.get('author')!=self.agent or event.get('room')!=record['room']
                            or event.get('source')!=record['payload']['sourceEventId']
                            or data.get('itemId')!=record['payload']['itemId'] or data.get('phase')!=record['payload']['phase']):
                        raise ValueError('Native observation receipt changed scope')
                    saved(path,{**record,'state':'accepted','receipt':receipt});self.pending.discard(path);delay=1
                except HttpFailure as error:
                    if error.status in (400,401,403,409):
                        saved(path,{**record,'state':'blocked','error':error.public_details()});self.pending.discard(path)
                    else:pending=True
                except Exception:pending=True
            if pending:
                await asyncio.sleep(delay*random.uniform(.8,1.2));delay=min(60,delay*2);self.wake.set()

    async def close(self):
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True);self.task=None
