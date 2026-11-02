"""Coalesced native status/liveness observations; never samples or wakes a model."""
from .runtime_files import state_directory
import asyncio,json,time
from pathlib import Path
from .journal import saved
from .errors import HttpFailure

class RoomNativeState:
    def __init__(self,*,state,thread,agent,rooms,send,authority=None,now=time.time):
        self.state=Path(state);state_directory(self.state, parents=True,exist_ok=True)
        self.thread,self.agent,self.rooms,self.send=thread,agent,[dict(r) for r in rooms],send
        self.status={'type':'unavailable','activeFlags':[]};self.source=None
        self.authority,self.now=authority,now
        self.wake=asyncio.Event();self.task=None
        self.inflight={};self.posts=asyncio.Semaphore(4);self.reads=asyncio.Semaphore(2)

    def set_rooms(self,rooms):
        previous={r['roomId']:r.get('membershipRevision') for r in self.rooms}
        self.rooms[:]=[dict(r) for r in rooms]
        joined={r['roomId'] for r in rooms}
        for identity,task in list(self.inflight.items()):
            if identity not in joined:task.cancel()
        if any(previous.get(r['roomId'])!=r.get('membershipRevision') for r in rooms):self.wake.set()

    async def request(self,method,path,payload):
        async with self.reads if method=='GET' else self.posts:
            if method=='POST' and {k:payload[k] for k in ('sourceEventId','status')}!=self.desired(path.split('/')[1]):
                self.wake.set();return None  # Reconcile/supersede next pass; never dispatch known obsolete metadata.
            return await asyncio.wait_for(self.send(method,path,payload),10)

    async def recover(self,room,old,path):
        """Revalidate metadata authority, never re-admit an original native input."""
        rejected=old['rejected'];identity=room['roomId']
        changed=room.get('membershipRevision')!=rejected.get('membershipRevision')
        if not changed and self.now()<rejected['nextCheckAt']:return False
        # A bad payload is not repaired by repeatedly trying it unchanged.
        if (rejected['status']==400 and not changed
                and self.desired(identity)==rejected['desired']):return False
        try:
            reply=await self.request('GET','rooms/'+identity,None)
            if (not self.authority or reply.get('authorityId')!=self.authority
                    or reply.get('room',{}).get('id')!=identity
                    or reply['room'].get('authority')!=self.authority):
                raise ValueError('Native recovery room scope changed')
            members=[m for m in reply.get('memberships',[]) if m.get('principal')==self.agent
                     and m.get('room')==identity and m.get('authority')==self.authority]
            if (len(members)!=1 or members[0].get('can_read') is not True
                    or members[0].get('can_post') is not True
                    or reply.get('permissions',{}).get('can_post') is not True):
                raise PermissionError('Native observation membership is not writable')
            native=reply.get('nativeState',{})
            if native.get('version')!=1:raise ValueError('Native recovery contract unavailable')
            rows=[a for a in native.get('agents',[]) if a.get('agentId')==self.agent
                  and a.get('nativeThread')==self.thread]
            if len(rows)>1:raise ValueError('Ambiguous native observation identity')
            revision=rows[0]['revision'] if rows else 0
            if type(revision) is not int or not 0<=revision<9007199254740991:
                raise ValueError('Invalid canonical observation revision')
            # The rejected payload/error stays in its original rejection receipt.
            # Publish a NEW current observation, not an input/tool/turn replay.
            saved(path,{'journalVersion':2,'revision':max(old['revision'],revision),
                        'recovery':{'canonicalRevision':revision,'membershipRevision':members[0]['revision'],
                                    'rejectedRevision':old['pending']['revision']}})
            return True
        except Exception as error:
            rejected.update(attempts=rejected['attempts']+1,
                            nextCheckAt=self.now()+min(300,25*2**min(rejected['attempts'],4)),
                            membershipRevision=room.get('membershipRevision'),lastReadError=type(error).__name__)
            saved(path,old)
            return False

    async def flush_room(self,room):
            identity=room['roomId'];path=self.state/(identity+'.json')
            old=json.loads(path.read_text()) if path.exists() else {'revision':0}
            pending=old.get('pending')
            if pending and not old.get('rejected'):
                desired={k:pending[k] for k in ('sourceEventId','status')}
                error_path=self.state/(identity+'-error.json')
                error=json.loads(error_path.read_text()) if error_path.exists() else {}
                status=error.get('error',{}).get('status') if isinstance(error.get('error'),dict) else None
                # Old SDKs persisted only pending + a separate error and kept
                # blocking in memory. Also supersede an unknown ACK if its
                # observation is now obsolete: it is metadata, not a command.
                if desired!=self.desired(identity) or old.get('journalVersion')!=2 and status in (400,401,403,409):
                    archive=self.state/(identity+'-legacy-pending-'+str(pending['revision'])+'.json')
                    if not archive.exists():saved(archive,{'original':old,'error':error,'nativeWorkReplayed':False})
                    old['rejected']={'status':status,'desired':desired,'membershipRevision':None,
                                     'attempts':0,'nextCheckAt':self.now(),'legacy':True}
                    saved(path,old)
            if old.get('rejected'):
                if not await self.recover(room,old,path):return
                old=json.loads(path.read_text())
            pending=old.get('pending')
            if pending is None:
                pending={'observationType':'nativeState','nativeThread':self.thread,'revision':old['revision']+1,
                         **self.desired(identity)}
                saved(path,{'journalVersion':2,'revision':pending['revision'],'pending':pending})
            try:
                reply=await self.request('POST','rooms/'+identity+'/activity',pending)
                if reply is None:return
                if (not reply.get('accepted') or reply.get('agentId')!=self.agent or reply.get('roomId')!=identity
                        or reply.get('nativeThread')!=self.thread or reply.get('revision')!=pending['revision']
                        or self.authority is not None and reply.get('authorityId')!=self.authority):
                    raise ValueError('Native status receipt changed scope')
                saved(path,{'journalVersion':2,'revision':pending['revision'],'accepted':reply})
                if any(pending[key]!=value for key,value in self.desired(identity).items()):self.wake.set()
            except HttpFailure as error:
                details={'error':error.public_details(),'nativeWorkReplayed':False}
                if error.status in (400,401,403,409):
                    rejected={'status':error.status,'desired':{k:pending[k] for k in ('sourceEventId','status')},
                              'membershipRevision':room.get('membershipRevision'),'attempts':0,
                              'nextCheckAt':self.now()+25}
                    receipt=self.state/(identity+'-rejected-'+str(pending['revision'])+'.json')
                    if not receipt.exists():saved(receipt,{'pending':pending,**details})
                    saved(path,{'journalVersion':2,'revision':pending['revision'],'pending':pending,'rejected':rejected})
                saved(self.state/(identity+'-error.json'),details)
            except Exception as error:
                saved(self.state/(identity+'-error.json'),{'error':type(error).__name__,'nativeWorkReplayed':False})

    async def flush(self,*,wait=True):
        scheduled=[]
        for room in list(self.rooms):
            identity=room['roomId'];task=self.inflight.get(identity)
            if task is None or task.done():
                task=asyncio.create_task(self.flush_room(room));self.inflight[identity]=task
                def finished(done,identity=identity):
                    if self.inflight.get(identity) is done:self.inflight.pop(identity,None)
                    if not done.cancelled() and done.exception():
                        saved(self.state/(identity+'-error.json'),{'error':type(done.exception()).__name__,'nativeWorkReplayed':False})
                task.add_done_callback(finished)
            scheduled.append(task)
        if wait:await asyncio.gather(*scheduled)

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
            # Slow quarantined-room recovery cannot delay healthy heartbeats.
            # One in-flight operation per room, <=2 reads and <=4 writes total.
            await self.flush(wait=False)

    async def close(self):
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True);self.task=None
        for task in self.inflight.values():task.cancel()
        await asyncio.gather(*self.inflight.values(),return_exceptions=True);self.inflight.clear()
