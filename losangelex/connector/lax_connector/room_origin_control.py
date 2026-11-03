"""Reconcile logical sessions on the existing catalog/reconnect boundary.

No models/new timers. Retain exact operation on restart. Known unstarted/read-only
phases can continue after prerequisite change/backoff; unknown thread/start is held.
"""
import asyncio,hashlib,json,time
from pathlib import Path
from uuid import UUID,uuid5
from .journal import saved
from .runtime_files import state_directory
from .room_administration import RoomAdministration,FACTORY_TOOL


def recovery(config,slot):
    directory=Path(config['state'])/'room-origin-factory'/('room-origin-'+slot['agent'])
    spec=directory/'spec.private.json';native=None
    if spec.exists():
        try:
            value=json.loads(spec.read_text());file=Path(value['connectorConfig']['state'])/'native-context.json'
            if file.exists():native=json.loads(file.read_text())
        except (KeyError,ValueError,OSError):return False,'unreadable-original-spec'
    if native and native.get('state')!='ready' and native.get('threadStartAttempted') is not False:
        return False,'original-native-delivery-unknown'
    parts=[slot['revision']]
    # Public filesystem/protected policy identities only, never auth contents.
    paths=[Path(__file__).with_name('room_factory_'+{'linux':'linux','darwin':'macos','win32':'windows'}.get(__import__('sys').platform,'unsupported')+'.py')]
    selection=config.get('roomOriginPolicy',{});paths.append(Path(selection.get('path','/nonexistent-room-policy')))
    manifest=config.get('nativeServer',{}).get('manifest')
    if manifest:paths.append(Path(manifest))
    for path in paths:
        try:
            info=path.stat();parts.append([str(path),info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns])
            if str(path)==manifest:
                socket=Path(json.loads(path.read_text())['socket'])
                try:
                    si=socket.stat();parts.append([si.st_dev,si.st_ino,si.st_mtime_ns])
                except OSError:parts.append('native-socket-unavailable')
        except OSError:parts.append([str(path),'unavailable'])
    if native:parts.append([native.get('state'),native.get('threadStartAttempted')])
    return True,hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest()


class RoomOriginControl:
    def __init__(self,*,config,request,thread,state,session_supervisor=None,now=time.time):
        self.config,self.request,self.thread=config,request,thread
        self.supervisor=session_supervisor;self.now=now
        self.state=Path(state);state_directory(self.state,parents=True,exist_ok=True)
        self.active={};self.capacity=asyncio.Semaphore(1)

    async def diagnose(self,slot,key,attempt,state,note):
        if self.request is None:return
        file=self.state/(key+'-diagnostic-'+str(attempt)+'-'+state+'.json')
        try:
            base='rooms/'+slot['room']+'/environment-agents'
            current=await self.request('GET',base)
            if current.get('capabilities',{}).get('controlStatus')!=1:return
            own=next(r for r in current['agents'] if r['agent']==slot['agent'] and r['coordinator']==self.config['agentId'])
            payload={'revision':own['control_revision']+1,'state':state,'note':note[:1000],
                     'originalOperation':'room-origin:'+key}
            if file.exists():
                original=json.loads(file.read_text())
                if original.get('accepted'):return
                if own.get('control_status')==original['payload']:
                    saved(file,{**original,'accepted':True,'reconciled':True});return
                # Diagnostic metadata may be superseded at its current revision;
                # never changes/replays the native/administrative workflow.
                archive=file.with_suffix('.unconfirmed.json')
                if not archive.exists():saved(archive,original)
            saved(file,{'payload':payload,'accepted':False})
            receipt=await self.request('POST',base+'/'+slot['node']+'/control-status',payload)
            if (receipt.get('accepted') is not True or receipt.get('coordinatorId')!=self.config['agentId']
                or receipt.get('revision')!=payload['revision'] or receipt.get('status')!=payload):
                raise ValueError('Original own-host diagnostic receipt differs')
            saved(file,{'payload':payload,'accepted':True,'receipt':receipt})
        except Exception as error:
            saved(self.state/(key+'-diagnostic-error.json'),{'errorType':type(error).__name__,
                'nativeOperationReplayed':False,'meaning':'Preparation status unavailable, no readiness inferred'})

    def observe(self,catalog):
        if catalog.get('authorityId')!=self.config['authorityId']:raise ValueError('Room-origin desired metadata crossed authority')
        if self.supervisor:self.supervisor.checkpoint()
        node=self.config.get('nodeId',self.config['hostId'])
        for slot in catalog.get('roomAgentInitializations',[]):
            if slot['node']!=node or slot['state'] not in ('pending','enrolled','blocked','unknown') or slot.get('receipt'):continue
            key=hashlib.sha256((slot['room']+'\0'+node+'\0'+slot['agent']).encode()).hexdigest();file=self.state/(key+'.json')
            if key in self.active:continue
            old=json.loads(file.read_text()) if file.exists() else None
            safe,fingerprint=recovery(self.config,slot)
            if not safe:continue  # Never infer absence from missing HTTP/native ACK.
            if old and old['state']=='reported':continue
            if old and old.get('prerequisite')==fingerprint and self.now()<old.get('nextCheckAt',0):continue
            attempts=(old or {}).get('attempts',0)+1
            record={'state':'accepted-control-intent','slot':slot,'modelCalls':0,'attempts':attempts,
                    'prerequisite':fingerprint,'nextCheckAt':self.now()+min(300,25*2**min(attempts-1,4))}
            if old:
                # Preserve every failed attempt before advancing this original
                # component's current inspection cursor; no new operation ID.
                archive=self.state/(key+'-attempt-'+str(old.get('attempts',0))+'.json')
                if not archive.exists():saved(archive,old)
            saved(file,record)
            async def run(key=key,file=file,slot=slot,record=record):
                try:
                    async with self.capacity:
                        await self.diagnose(slot,key,record['attempts'],'preparing',
                            'Original home runtime is reconciling this logical agent; no native readiness inferred')
                        admin=RoomAdministration(authority=self.config['authorityId'],agent=self.config['agentId'],
                            thread=self.thread,request=self.request,state=self.state/key,host_config=self.config,
                            session_supervisor=self.supervisor)
                        result=await admin.call(FACTORY_TOOL,{'roomId':slot['room']},'room-origin:'+key)
                        saved(file,{**record,'state':'reported','result':result})
                except asyncio.CancelledError:raise
                except Exception as error:
                    safe,_=recovery(self.config,slot)
                    cause=error
                    while cause.__cause__ is not None:cause=cause.__cause__
                    note=(str(cause) if isinstance(cause,PermissionError) else
                          'Original initialization requires exact receipt inspection; retained '+type(cause).__name__)
                    await self.diagnose(slot,key,record['attempts'],'blocked' if safe else 'unknown',note)
                    saved(file,{**record,'state':'recoverable' if safe else 'held','reason':str(error)[:1000],
                                'errorType':type(error).__name__})
                finally:self.active.pop(key,None)
            self.active[key]=asyncio.create_task(run())

    async def close(self):
        for task in self.active.values():task.cancel()
        await asyncio.gather(*list(self.active.values()),return_exceptions=True)
