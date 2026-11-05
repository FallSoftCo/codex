"""Many logical agent sessions in ONE existing host runtime/event loop.

No child processes, OS services or native daemons. Session/thread/config bindings
are durable; ordinary parent restart resumes only registered original threads.
"""
import asyncio,json,os,time
from pathlib import Path
from .journal import saved
from .runtime_files import state_directory,private_file
from .room_session_files import digest_file,host_policy,parent_admission_revision


class RoomSessionSupervisor:
    def __init__(self,parent,*,session_factory=None,now=time.monotonic):
        self.parent=parent;self.config=parent.config
        self.state=Path(self.config['state'])/'room-sessions';state_directory(self.state,parents=True,exist_ok=True)
        self.sessions={};self.tasks={};self.records={};self.closed=False
        self.session_factory=session_factory;self.now=now
        self.parent_deferred={};self.admission_revision=None
        self.admission_next_check=0.;self.admission_checks=0

    def snapshot(self):
        rows=[]
        for agent,record in self.records.items():
            session=self.sessions.get(agent);task=self.tasks.get(agent)
            state=('clients-closed' if self.closed else record['state'] if record.get('state') in ('blocked','stopped')
                   else 'attached' if task and not task.done() else 'pending')
            live=session is not None and state=='attached'
            row={'agentId':agent,'originRoomId':record['originRoomId'],'nativeThreadId':record['nativeThreadId'],
                 'parentRuntimePid':os.getpid(),'state':state,
                 'nativeStatus':session.native_state.status['type'] if live else 'unavailable',
                 'activeTurn':bool(live and session.native_active_turn),
                 'outputsPending':len(session.conversation_io.pending()) if live else None,
                 'errorType':record.get('errorType')}
            # This is an owner-private release/inspection view, not another
            # room's public native source/status projection.
            rows.append(row)
        return {'schema':'lax-host-logical-sessions/v1','parentRuntimePid':os.getpid(),'sessions':rows,
                'runtimeCapabilities':['project-role-handover/v1'],
                'quiet':all(r['state']=='attached' and r['nativeStatus']=='idle' and
                            not r['activeTurn'] and r['outputsPending']==0 for r in rows)}

    def checkpoint(self):saved(self.state/'status.private.json',self.snapshot())

    def _load_record(self,file,expected=None):
        agent=file.stem.removeprefix('session-')
        if agent in self.tasks:return  # includes failed/stopped original clients
        try:
            private_file(file);record=json.loads(file.read_text())
            if record['agentId']!=agent or expected is not None and record!=expected:
                raise ValueError('Original deferred logical session registration changed')
            if record.get('state') in ('blocked','stopped'):
                self.records[agent]=record;return  # an explicit local stop is not parent deferral
            self._attach(record)
        except Exception as error:
            self.records[agent]={'originRoomId':'unavailable','nativeThreadId':'unavailable',
                                 'state':'blocked','errorType':type(error).__name__}
            saved(self.state/('load-failure-'+agent+'.json'),self.records[agent])
            return error

    def _admission_failed(self,error):
        saved(self.state/'admission-blocked.private.json',{'state':'blocked','parentRuntimePid':os.getpid(),
            'errorType':type(error).__name__,'admissionAllowed':False})
        self.admission_checks+=1
        self.admission_next_check=self.now()+min(300,25*2**min(self.admission_checks-1,4))
        self.admission_revision=parent_admission_revision(self.config)

    def load(self):
        if self.closed:raise RuntimeError('Original host supervisor is closing')
        if not self.config.get('roomOriginPolicy'):
            if any(self.state.glob('session-*.json')):
                raise PermissionError('Original resident session policy is missing; do not abandon registered actors')
            return
        try:host_policy(self.config)
        except Exception as error:
            self._admission_failed(error)
            # Only registrations which have NEVER attached in this parent can
            # be deferred. A later closure never relabels running/failed siblings.
            for file in sorted(self.state.glob('session-*.json')):
                try:
                    private_file(file);record=json.loads(file.read_text());agent=record['agentId']
                    if agent!=file.stem.removeprefix('session-') or agent in self.tasks:continue
                    previous=self.records.get(agent,{})
                    if (record.get('state') in ('blocked','stopped') or
                        previous.get('state') in ('blocked','stopped') and
                        previous.get('errorType')!='ParentAdmissionUnavailable'):continue
                    self.parent_deferred[agent]=record
                    self.records[agent]={**record,'state':'blocked','errorType':'ParentAdmissionUnavailable'}
                except Exception:continue
            self.checkpoint();return
        for file in sorted(self.state.glob('session-*.json')):self._load_record(file)
        self.parent_deferred.clear();self.checkpoint()

    def reconcile_admission(self):
        """Existing catalog/reconnect edge, ONLY known parent-deferred records.

        No native thread/start, model wake, timer or service control. A changed
        protected owner record allows an immediate full revalidation; otherwise
        bounded event-driven backoff covers repaired read-only prerequisites.
        """
        if self.closed or not self.parent_deferred:return False
        revision=parent_admission_revision(self.config)
        if revision==self.admission_revision and self.now()<self.admission_next_check:return False
        try:host_policy(self.config)
        except Exception as error:
            self._admission_failed(error);self.checkpoint();return False
        restored=[]
        for agent,record in list(self.parent_deferred.items()):
            error=self._load_record(self.state/('session-'+agent+'.json'),expected=record)
            if error and agent not in self.tasks:
                try:host_policy(self.config)
                except Exception as parent_error:
                    # Owner admission can close while the next registration is
                    # validated. Preserve that never-attached original, not a
                    # separately failed session and not a new native operation.
                    self.records[agent]={**record,'state':'blocked','errorType':'ParentAdmissionUnavailable'}
                    self._admission_failed(parent_error);self.checkpoint();return False
            self.parent_deferred.pop(agent,None)
            if agent in self.tasks:restored.append(agent)
        saved(self.state/'admission-reconciled.private.json',{'state':'reconciled','parentRuntimePid':os.getpid(),
            'restoredAgentIds':restored,'ownerRecordRevision':revision,
            'meaning':'Original deferred registrations only; no new native threads or admission minted'})
        self.checkpoint();return True

    def attach(self,result):
        if self.closed:raise RuntimeError('Original host supervisor is closing')
        if result.get('state')!='ready' or result.get('sharedAppServer') is not True:
            raise ValueError('Accepted shared native bootstrap required')
        record={k:result[k] for k in ('agentId','originRoomId','nativeThreadId','sessionConfigPath','sessionConfigSha256')}
        file=self.state/('session-'+record['agentId']+'.json')
        if file.exists():
            old=json.loads(file.read_text())
            from .project_adoption import accepts_initialization
            if not accepts_initialization(record,old):raise ValueError('Original resident agent binding changed')
            self._validate(old)
            record=old
        else:
            self._validate(record)
            saved(file,record)
        self._attach(record)

    def _validate(self,record):
        from .project_adoption import role_receipt
        role_receipt(record)
        policy,_=host_policy(self.config);file=Path(record['sessionConfigPath']);private_file(file)
        if digest_file(file)!=record['sessionConfigSha256']:raise ValueError('Original logical session config changed')
        config=json.loads(file.read_text())
        if (config['agentId']!=record['agentId'] or config['originRoomId']!=record['originRoomId'] or
            config['nativeThreadId']!=record['nativeThreadId'] or
            config['nativeThreadId']==self.parent.thread or config['agentId']==self.config['agentId'] or
            config['nativeServer']!=self.config['nativeServer'] or config['codexHome']!=self.config['codexHome'] or
            config['authorityId']!=self.config['authorityId'] or config['hostId']!=self.config['hostId']):
            raise ValueError('Original parent/agent/room/native binding differs')
        for key in ('state','workspace'):
            p=Path(config[key]);expected=Path(policy['root'])/config['agentId']/('state' if key=='state' else policy.get('workspaceRelative','work'))
            if p!=expected or p.resolve()!=p:raise ValueError('Protected original room session path required')
        if any(r['nativeThreadId']==record['nativeThreadId'] and a!=record['agentId'] for a,r in self.records.items()):
            raise ValueError('Native context already belongs to another logical agent')
        return config

    def _attach(self,record):
        agent=record['agentId']
        if agent in self.tasks:return  # no second instance, including failed one
        config=self._validate(record)
        if self.session_factory is None:
            from .conversational_agent import ConversationalAgent
            factory=ConversationalAgent
        else:factory=self.session_factory
        session=factory(config);session.host_supervisor=self;self.sessions[agent]=session;self.records[agent]=record
        async def run():
            try:await session.serve()
            except asyncio.CancelledError:raise
            except Exception as error:
                # A sibling or parent is never cancelled by this session fault.
                self.records[agent]={**record,'state':'blocked','errorType':type(error).__name__}
                saved(self.state/('failure-'+agent+'.json'),self.records[agent])
            finally:
                if self.records[agent].get('state')!='blocked':self.records[agent]={**record,'state':'stopped'}
                self.checkpoint()
        self.tasks[agent]=asyncio.create_task(run());self.checkpoint()

    async def close(self):
        self.closed=True
        for task in self.tasks.values():task.cancel()
        await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        self.checkpoint()
