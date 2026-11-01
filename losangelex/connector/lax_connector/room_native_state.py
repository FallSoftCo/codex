"""Coalesced native status/liveness observations; never samples or wakes a model."""
from .runtime_files import state_directory
import asyncio,json
from pathlib import Path
from .journal import saved
from .errors import HttpFailure

class RoomNativeState:
    def __init__(self,*,state,thread,agent,rooms,send):
        self.state=Path(state);state_directory(self.state, parents=True,exist_ok=True)
        self.thread,self.agent,self.rooms,self.send=thread,agent,[dict(r) for r in rooms],send
        self.status={'type':'unavailable','activeFlags':[]};self.source=None
        self.wake=asyncio.Event();self.task=None;self.blocked=set()

    def update(self,status,source):
        # Preserve precisely the native status/flags; do not infer completion
        # from last message, silence, action captions or a delivered answer.
        if status!=self.status or source!=self.source:
            self.status=dict(status);self.source=source;self.wake.set()

    def desired(self,room):
        source=self.source if self.source and self.source['room']==room else None
        status=self.status if self.status['type']!='active' or source else {'type':'unavailable','activeFlags':[]}
        return {'sourceEventId':source['id'] if source else None,'status':status}

    def start(self):
        if self.task:raise RuntimeError('Native status observer already started')
        self.task=asyncio.create_task(self.run());self.wake.set()

    async def run(self):
        while True:
            try:await asyncio.wait_for(self.wake.wait(),25)
            except asyncio.TimeoutError:pass  # A cheap transport heartbeat, not inference or native RPC polling.
            self.wake.clear()
            for room in self.rooms:
                identity=room['roomId']
                if identity in self.blocked:continue
                path=self.state/(identity+'.json')
                old=json.loads(path.read_text()) if path.exists() else {'revision':0}
                pending=old.get('pending')
                if pending is None:
                    pending={'observationType':'nativeState','nativeThread':self.thread,'revision':old['revision']+1,
                             **self.desired(identity)}
                    saved(path,{'revision':pending['revision'],'pending':pending})
                try:
                    reply=await asyncio.wait_for(self.send('POST','rooms/'+identity+'/activity',pending),10)
                    if (not reply.get('accepted') or reply.get('agentId')!=self.agent or reply.get('roomId')!=identity
                            or reply.get('nativeThread')!=self.thread or reply.get('revision')!=pending['revision']):
                        raise ValueError('Native status receipt changed scope')
                    saved(path,{'revision':pending['revision'],'accepted':reply})
                    if any(pending[key]!=value for key,value in self.desired(identity).items()):self.wake.set()
                except HttpFailure as error:
                    if error.status in (400,401,403,409):self.blocked.add(identity)
                    saved(self.state/(identity+'-error.json'),{'error':error.public_details(),'nativeWorkReplayed':False})
                except Exception as error:
                    saved(self.state/(identity+'-error.json'),{'error':type(error).__name__,'nativeWorkReplayed':False})

    async def close(self):
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True);self.task=None
