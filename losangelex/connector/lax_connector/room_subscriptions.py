"""Room membership discovery and SSE ownership; it never samples a model.

Catalog visibility is NOT membership (especially for administrators). Only
explicit canonical membership can add a listening room. An outage or absent
catalog row never revokes an existing listener.
"""
from .runtime_files import state_directory
import asyncio,json,time
from pathlib import Path
from uuid import UUID
from .journal import saved

class RoomSubscriptions:
    def __init__(self,*,state,authority,agent,thread,rooms,request,create,on_rooms,now=time.time):
        self.state=Path(state);state_directory(self.state, parents=True,exist_ok=True)
        self.binding={'authority':authority,'agent':agent,'thread':thread}
        self.authority,self.request,self.create,self.on_rooms=authority,request,create,on_rooms
        self.known={r['roomId']:{'after':r['after'],'revision':None,'member':True} for r in rooms}
        path=self.state/'memberships.json'
        if path.exists():
            old=json.loads(path.read_text())
            if old['binding']!=self.binding:raise ValueError('Room subscriptions belong to another authority')
            for room,value in old['rooms'].items():self.known[room]=value
        self.live={};self.status={};self.lock=asyncio.Lock();self.wake=asyncio.Event()
        self.now=now;self.recovery={};self.recovering={};self.reads=asyncio.Semaphore(2)
        for room in self.known:
            path=self.state/(room+'-status.json')
            legacy=self.state.parent/('room-'+room+'-status.json')
            if path.exists() or legacy.exists():
                value=json.loads((path if path.exists() else legacy).read_text())
                if value.get('roomId')==room:self.status[room]=value

    def note(self,value):
        room=value['roomId'];self.status[room]=value
        if value['state']=='connected':self.recovery.pop(room,None)
        elif value.get('httpStatus') in (401,403):
            old=self.recovery.get(room,{'attempts':0})
            self.recovery[room]={'attempts':old['attempts']+1,
                'nextCheckAt':self.now()+min(300,25*2**min(old['attempts'],4))}
        saved(self.state/(room+'-status.json'),value)

    def persist(self):
        saved(self.state/'memberships.json',{'binding':self.binding,'rooms':self.known})
        self.on_rooms([{'roomId':room,'after':value['after'],'membershipRevision':value['revision']}
                       for room,value in self.known.items() if value['member']])

    def start_room(self,room):
        if self.status.get(room,{}).get('state')=='needs_reconciliation':return
        prior=self.live.get(room)
        if prior and not prior[1].done():return
        if prior:prior[0].close();self.live.pop(room,None)
        listener=self.create(room,self.known[room]['after'])
        if listener.journal.has_unresolved(self.binding['authority'],self.binding['agent']):
            self.note({'roomId':room,'state':'needs_reconciliation','reason':'Original native handoff remains unresolved'})
            listener.close();return
        async def listen():
            try:await listener.run()
            except asyncio.CancelledError:raise
            except Exception as error:
                self.note({'roomId':room,'state':'blocked','reason':type(error).__name__})
                saved(self.state/(room+'-error.json'),self.status[room])
        self.live[room]=(listener,asyncio.create_task(listen()))

    def recover_room(self,room):
        if room in self.recovering:return
        old=self.recovery.get(room,{'attempts':0,'nextCheckAt':0})
        if self.now()<old['nextCheckAt']:return
        async def recover():
            try:
                async with self.reads:
                    value=await asyncio.wait_for(self.request('GET','rooms/'+room),10)
                if (value.get('authorityId')!=self.authority or value.get('room',{}).get('id')!=room
                        or value['room'].get('authority')!=self.authority):raise ValueError('Recovery scope changed')
                members=[m for m in value.get('memberships',[]) if m.get('principal')==self.binding['agent']
                         and m.get('room')==room and m.get('authority')==self.authority]
                if (len(members)!=1 or members[0].get('can_read') is not True
                        or value.get('permissions',{}).get('can_read') is not True):
                    raise PermissionError('Current room read membership denied')
                async with self.lock:
                    current=self.known.get(room)
                    if not current or not current['member'] or self.status.get(room,{}).get('state')=='needs_reconciliation':return
                    if current['revision']!=members[0]['revision']:
                        self.wake.set();return  # Reconcile the current membership, never guess a grant.
                    self.start_room(room)  # Original persisted cursor and receive journal.
            except asyncio.CancelledError:raise
            except Exception as error:
                self.recovery[room]={'attempts':old['attempts']+1,
                    'nextCheckAt':self.now()+min(300,25*2**min(old['attempts'],4))}
                saved(self.state/(room+'-recovery.json'),{**self.recovery[room],
                    'error':type(error).__name__,'nativeWorkReplayed':False})
            finally:self.recovering.pop(room,None)
        self.recovering[room]=asyncio.create_task(recover())

    async def refresh(self):
        async with self.lock:
            result=await asyncio.wait_for(self.request('GET','rooms'),15)
            if result.get('authorityId')!=self.authority:raise ValueError('Room catalog authority changed')
            for row in result['rooms']:
                if row.get('authority')!=self.authority:raise ValueError('Room membership crossed authority')
                if row.get('membershipVersion')!=1:continue  # Compatibility: keep configured rooms, never guess membership.
                room=str(UUID(row['id']));member=row.get('memberCanRead');revision=row.get('membershipRevision')
                if type(member) is not bool or type(revision) is not int or revision<0:raise ValueError('Invalid canonical room membership')
                prior=self.known.get(room)
                changed=not prior or prior['revision']!=revision or prior['member']!=member
                if not prior and not member:continue
                self.known[room]={'after':prior['after'] if prior else 0,'revision':revision,'member':member}
                if not member:
                    old=self.live.pop(room,None)
                    if old:
                        old[1].cancel();await asyncio.gather(old[1],return_exceptions=True);old[0].close()
                    self.note({'roomId':room,'state':'blocked','reason':'Canonical read membership revoked','httpStatus':403})
                else:
                    # An unresolved original native input is never retried merely
                    # because a membership/catalog refresh happened.
                    status=self.status.get(room,{})
                    if status.get('state')=='needs_reconciliation':continue
                    listener=self.live.get(room)
                    if status.get('state')=='blocked':
                        if changed:self.recovery[room]={'attempts':0,'nextCheckAt':0}
                        if status.get('httpStatus') in (401,403) or changed:self.recover_room(room)
                    elif changed or listener is None:self.start_room(room)
            self.persist()

    async def run(self):
        self.persist()
        for room,value in self.known.items():
            if value['member'] and self.status.get(room,{}).get('state')!='blocked':self.start_room(room)
        while True:
            try:await self.refresh()
            except asyncio.CancelledError:raise
            except Exception as error:saved(self.state/'discovery-error.json',{'error':type(error).__name__,'nativeWorkReplayed':False})
            try:await asyncio.wait_for(self.wake.wait(),25)
            except asyncio.TimeoutError:pass
            self.wake.clear()

    async def close(self):
        for task in self.recovering.values():task.cancel()
        await asyncio.gather(*self.recovering.values(),return_exceptions=True);self.recovering.clear()
        for listener,task in self.live.values():task.cancel()
        await asyncio.gather(*(task for listener,task in self.live.values()),return_exceptions=True)
        for listener,task in self.live.values():listener.close()
        self.live.clear()
