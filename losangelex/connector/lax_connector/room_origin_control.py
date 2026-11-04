"""Reconcile logical sessions on the existing catalog/reconnect boundary.

No models/new timers. Retain exact operation on restart. Known unstarted/read-only
phases can continue after prerequisite change/backoff; unknown thread/start is held.
"""
import asyncio,hashlib,json,time
from pathlib import Path
from uuid import UUID,uuid5
from .journal import saved
from .runtime_files import state_directory
from .room_administration import RoomAdministration,FACTORY_TOOL,digest


def recovery(config,slot,placement=None,enrollment=None):
    directory=Path(config['state'])/'room-origin-factory'/('room-origin-'+slot['agent'])
    spec=directory/'spec.private.json';native=None
    if spec.exists():
        try:
            value=json.loads(spec.read_text());file=Path(value['connectorConfig']['state'])/'native-context.json'
            if file.exists():native=json.loads(file.read_text())
        except (KeyError,ValueError,OSError):return False,'unreadable-original-spec'
    if native and native.get('state')!='ready' and native.get('threadStartAttempted') is not False:
        return False,'original-native-delivery-unknown'
    dispatch=directory/'dispatch.json'
    if dispatch.exists() and json.loads(dispatch.read_text()).get('state')=='unknown' and not native:
        return False,'original-platform-delivery-unknown-no-unstarted-proof'
    parts=[slot['revision']]
    if placement is not None:parts.append(placement)
    if enrollment is not None:parts.append(enrollment)
    from .room_session_files import parent_admission_revision
    parts.append(['parentAcceptance',parent_admission_revision(config)])
    # Public filesystem/protected policy identities only, never auth contents.
    paths=[Path(__file__).with_name('room_factory_'+{'linux':'linux','darwin':'macos','win32':'windows'}.get(__import__('sys').platform,'unsupported')+'.py'),
           Path(__file__).with_name('room_initial_report.py'),Path(__file__).with_name('room_windows_initial_configuration.py')]
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


def enrollment_projection(config,slot,setup):
    """Stable canonical attachment facts; diagnostics/freshness are not wake edges."""
    if not isinstance(setup,dict) or setup.get('roomId')!=slot['room']:return None
    rows=[r for r in setup.get('agents',[]) if r.get('node')==slot['node'] and r.get('agent')==slot['agent']]
    if len(rows)!=1 or rows[0].get('coordinator')!=config['agentId']:return None
    row=rows[0]
    return {k:row.get(k) for k in ('identity_active','origin_room','origin_node','member',
                                   'coordinator_enabled','current_coordinator')}


class RoomOriginControl:
    def __init__(self,*,config,request,thread,state,session_supervisor=None,now=time.time):
        self.config,self.request,self.thread=config,request,thread
        self.supervisor=session_supervisor;self.now=now
        self.state=Path(state);state_directory(self.state,parents=True,exist_ok=True)
        self.active={};self.capacity=asyncio.Semaphore(1)
        self.metadata=set()

    def pending_enrollment(self,key,slot):
        """A reported observation is not acceptance of this retained sending step."""
        identity=str(uuid5(UUID(self.config['agentId']),digest([self.thread,'room-origin:'+key])))
        operation='native-admin:'+identity;binding={'authority':self.config['authorityId'],
            'agent':self.config['agentId'],'thread':self.thread}
        state=self.state/key;directory=state/digest(operation)
        try:
            workflow=json.loads((state/('workflow-'+identity+'.json')).read_text())
            pending=json.loads((state/'pending.json').read_text())
            step=json.loads((directory/'2.json').read_text())
            if (workflow.get('state') not in ('intent','unconfirmed') or workflow.get('tool')!=FACTORY_TOOL
                    or workflow.get('arguments')!={'roomId':slot['room']} or workflow.get('binding')!=binding
                    or workflow.get('operationId')!=operation or pending!={'operationId':operation,'binding':binding}
                    or step.get('state')!='sending'
                    or step.get('operationId')!='room-origin:'+str(uuid5(UUID(slot['agent']),'host-initialization'))+':enroll'
                    or any((directory/(str(i)+'.json')).exists() for i in range(3,8))):return False
            if any(json.loads((directory/(str(i)+'.json')).read_text()).get('state')!='accepted' for i in (0,1)):return False
            factory=Path(self.config['state'])/'room-origin-factory'/('room-origin-'+slot['agent'])
            return not (factory/'spec.private.json').exists() and not (factory/'dispatch.json').exists()
        except (OSError,KeyError,ValueError,TypeError):return False

    def changed_reported_enrollment(self,key,slot,old,enrollment):
        before=old.get('canonicalEnrollment') or enrollment_projection(self.config,slot,old.get('result'))
        return bool(before is not None and enrollment is not None and before!=enrollment
            and all(enrollment.get(k) is True for k in ('identity_active','member','coordinator_enabled'))
            and enrollment.get('origin_room')==slot['room'] and enrollment.get('origin_node')==slot['node']
            and enrollment.get('current_coordinator')==self.config['agentId'] and self.pending_enrollment(key,slot))

    async def parent_placement(self):
        """Read the existing parent enrollment; pause/revocation never admits setup."""
        from .placement_control import view
        try:
            value=view(await self.request('GET','placements/'+self.config['agentId']),
                self.config['authorityId'],self.config['agentId'],self.config['hostId'])
            row=value['placement']
            receipt={'state':value['state'],'hostId':value['hostId'],
                     'revision':row['revision'] if row else None,
                     'generation':row.get('generation') if row else None}
            file=self.state/'parent-placement.json'
            if not file.exists() or json.loads(file.read_text())!=receipt:saved(file,receipt)
            return receipt if value['state']=='enabled' else None
        except asyncio.CancelledError:raise
        except Exception as error:
            saved(self.state/'parent-placement-error.json',{'errorType':type(error).__name__,
                'status':getattr(error,'status',None),'code':getattr(error,'code',None),
                'factoryStarted':False})
            return None

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
        if self.supervisor:
            self.supervisor.reconcile_admission()
            self.supervisor.checkpoint()
        node=self.config.get('nodeId',self.config['hostId'])
        placement=None
        for slot in catalog.get('roomAgentInitializations',[]):
            if slot['node']!=node or slot['state'] not in ('pending','enrolled','blocked','unknown') or slot.get('receipt'):continue
            key=hashlib.sha256((slot['room']+'\0'+node+'\0'+slot['agent']).encode()).hexdigest();file=self.state/(key+'.json')
            if key in self.active:continue
            old=json.loads(file.read_text()) if file.exists() else None
            room=next((r for r in catalog.get('rooms',[]) if r.get('id')==slot['room']
                       and r.get('authority')==self.config['authorityId']),{})
            enrollment=enrollment_projection(self.config,slot,room.get('roomAgents'))
            safe,fingerprint=recovery(self.config,slot)
            if not safe:continue  # Never infer absence from missing HTTP/native ACK.
            resume_reported=bool(old and old['state']=='reported'
                and self.changed_reported_enrollment(key,slot,old,enrollment))
            if old and old['state']=='reported' and not resume_reported:
                from .room_initial_configuration import available
                operation='native-admin:'+str(uuid5(UUID(self.config['agentId']),digest([self.thread,'room-origin:'+key])))
                resume_reported=available(self.config,self.state/key,self.thread,operation)
            if old and old['state']=='reported' and not resume_reported:continue
            if (not self.supervisor and old and old.get('prerequisite')==fingerprint
                    and self.now()<old.get('nextCheckAt',0)):continue
            if self.supervisor and placement is None:
                # One bounded read on this existing catalog edge while paused,
                # not one polling loop/read per pending room.
                placement=asyncio.create_task(self.parent_placement())
                self.metadata.add(placement);placement.add_done_callback(self.metadata.discard)
            async def run(key=key,file=file,slot=slot,placement=placement,enrollment=enrollment,resume_reported=resume_reported):
                record=None
                try:
                    current=await asyncio.shield(placement) if placement else None
                    if placement and current is None:return
                    old=json.loads(file.read_text()) if file.exists() else None
                    safe,fingerprint=recovery(self.config,slot,current,enrollment)
                    if not safe or old and old['state']=='reported' and not resume_reported:return
                    if old and not resume_reported and old.get('prerequisite')==fingerprint and self.now()<old.get('nextCheckAt',0):return
                    async with self.capacity:
                        # A queued sibling must not use an enabled snapshot
                        # captured before a real user/maintenance pause.
                        if placement:
                            current=await self.parent_placement()
                            if current is None:return
                        safe,fingerprint=recovery(self.config,slot,current,enrollment)
                        if not safe:return
                        if resume_reported and not self.pending_enrollment(key,slot):
                            from .room_initial_configuration import available
                            operation='native-admin:'+str(uuid5(UUID(self.config['agentId']),digest([self.thread,'room-origin:'+key])))
                            if not available(self.config,self.state/key,self.thread,operation):return
                        attempts=(old or {}).get('attempts',0)+1
                        record={'state':'accepted-control-intent','slot':slot,'modelCalls':0,'attempts':attempts,
                            'prerequisite':fingerprint,'canonicalEnrollment':enrollment,
                            'nextCheckAt':self.now()+min(300,25*2**min(attempts-1,4))}
                        if old:
                            archive=self.state/(key+'-attempt-'+str(old.get('attempts',0))+'.json')
                            if not archive.exists():saved(archive,old)
                        saved(file,record)
                        await self.diagnose(slot,key,record['attempts'],'preparing',
                            'Original home runtime is reconciling this logical agent; no native readiness inferred')
                        if placement and await self.parent_placement() is None:
                            saved(file,{**record,'state':'placement-deferred'})
                            return  # A pause/revocation during diagnostic I/O is real.
                        admin=RoomAdministration(authority=self.config['authorityId'],agent=self.config['agentId'],
                            thread=self.thread,request=self.request,state=self.state/key,host_config=self.config,
                            session_supervisor=self.supervisor)
                        result=await admin.call(FACTORY_TOOL,{'roomId':slot['room']},'room-origin:'+key)
                        saved(file,{**record,'state':'reported','result':result})
                except asyncio.CancelledError:raise
                except Exception as error:
                    if record is None:
                        saved(self.state/(key+'-inspection-error.json'),{'errorType':type(error).__name__,
                            'factoryStarted':False})
                        return
                    safe,_=recovery(self.config,slot)
                    cause=error
                    while cause.__cause__ is not None:cause=cause.__cause__
                    public_platform=(type(cause).__module__ in ('lax_connector.room_factory_macos','lax_connector.room_factory_windows_state')
                                     and type(cause).__name__ in ('Hold','Held'))
                    note=(str(cause) if isinstance(cause,PermissionError) or public_platform else
                          'Original initialization requires exact receipt inspection; retained '+type(cause).__name__)
                    await self.diagnose(slot,key,record['attempts'],'blocked' if safe else 'unknown',note)
                    saved(file,{**record,'state':'recoverable' if safe else 'held','reason':str(error)[:1000],
                                'errorType':type(error).__name__})
                finally:self.active.pop(key,None)
            self.active[key]=asyncio.create_task(run())

    async def close(self):
        for task in self.metadata:task.cancel()
        for task in self.active.values():task.cancel()
        await asyncio.gather(*list(self.active.values()),*list(self.metadata),return_exceptions=True)
