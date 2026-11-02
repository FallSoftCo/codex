"""Room membership discovery and SSE ownership; it never samples a model.

Catalog visibility is NOT membership (especially for administrators). Only
explicit canonical membership can add a listening room. An outage or absent
catalog row never revokes an existing listener.
"""
from .runtime_files import state_directory
import asyncio,json
from pathlib import Path
from uuid import UUID
from .journal import saved

class RoomSubscriptions:
    def __init__(self,*,state,authority,agent,thread,rooms,request,create,on_rooms):
        self.state=Path(state);state_directory(self.state, parents=True,exist_ok=True)
        self.binding={'authority':authority,'agent':agent,'thread':thread}
        self.authority,self.request,self.create,self.on_rooms=authority,request,create,on_rooms
        self.known={r['roomId']:{'after':r['after'],'revision':None,'member':True} for r in rooms}
        path=self.state/'memberships.json'
        if path.exists():
            old=json.loads(path.read_text())
            if old['binding']!=self.binding:raise ValueError('Room subscriptions belong to another authority')
            for room,value in old['rooms'].items():self.known.setdefault(room,value)
        self.live={};self.status={};self.lock=asyncio.Lock();self.wake=asyncio.Event()

    def note(self,value):self.status[value['roomId']]=value

    def persist(self):
        saved(self.state/'memberships.json',{'binding':self.binding,'rooms':self.known})
        self.on_rooms([{'roomId':room,'after':value['after'],'membershipRevision':value['revision']}
                       for room,value in self.known.items() if value['member']])

    def start_room(self,room):
        prior=self.live.get(room)
        if prior and not prior[1].done():return
        if prior:prior[0].close()
        listener=self.create(room,self.known[room]['after'])
        async def listen():
            try:await listener.run()
            except asyncio.CancelledError:raise
            except Exception as error:
                self.status[room]={'state':'blocked','reason':type(error).__name__}
                saved(self.state/(room+'-error.json'),self.status[room])
        self.live[room]=(listener,asyncio.create_task(listen()))

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
                elif changed or room not in self.live:
                    # An unresolved original native input is never retried merely
                    # because a membership/catalog refresh happened.
                    if self.status.get(room,{}).get('state')!='needs_reconciliation':self.start_room(room)
            self.persist()

    async def run(self):
        self.persist()
        for room,value in self.known.items():
            if value['member']:self.start_room(room)
        while True:
            try:await self.refresh()
            except asyncio.CancelledError:raise
            except Exception as error:saved(self.state/'discovery-error.json',{'error':type(error).__name__,'nativeWorkReplayed':False})
            try:await asyncio.wait_for(self.wake.wait(),25)
            except asyncio.TimeoutError:pass
            self.wake.clear()

    async def close(self):
        for listener,task in self.live.values():task.cancel()
        await asyncio.gather(*(task for listener,task in self.live.values()),return_exceptions=True)
        for listener,task in self.live.values():listener.close()
        self.live.clear()
