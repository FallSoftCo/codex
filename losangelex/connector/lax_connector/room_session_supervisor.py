"""Many logical agent sessions in ONE existing host runtime/event loop.

No child processes, OS services or native daemons. Session/thread/config bindings
are durable; ordinary parent restart resumes only registered original threads.
"""
import asyncio,json,os
from pathlib import Path
from .journal import saved
from .runtime_files import state_directory,private_file
from .room_session_files import digest_file,host_policy


class RoomSessionSupervisor:
    def __init__(self,parent,*,session_factory=None):
        self.parent=parent;self.config=parent.config
        self.state=Path(self.config['state'])/'room-sessions';state_directory(self.state,parents=True,exist_ok=True)
        self.sessions={};self.tasks={};self.records={};self.closed=False
        self.session_factory=session_factory

    def snapshot(self):
        rows=[]
        for agent,record in self.records.items():
            session=self.sessions.get(agent);task=self.tasks.get(agent)
            row={'agentId':agent,'originRoomId':record['originRoomId'],'nativeThreadId':record['nativeThreadId'],
                 'parentRuntimePid':os.getpid(),'state':'attached' if task and not task.done() else record.get('state','pending'),
                 'nativeStatus':session.native_state.status['type'] if session else 'unavailable',
                 'activeTurn':bool(session and session.native_active_turn),
                 'outputsPending':len(session.conversation_io.pending()) if session else None,
                 'errorType':record.get('errorType')}
            # This is an owner-private release/inspection view, not another
            # room's public native source/status projection.
            rows.append(row)
        return {'schema':'lax-host-logical-sessions/v1','parentRuntimePid':os.getpid(),'sessions':rows,
                'quiet':all(r['state']=='attached' and r['nativeStatus']=='idle' and
                            not r['activeTurn'] and r['outputsPending']==0 for r in rows)}

    def checkpoint(self):saved(self.state/'status.private.json',self.snapshot())

    def load(self):
        if not self.config.get('roomOriginPolicy'):
            if any(self.state.glob('session-*.json')):
                raise PermissionError('Original resident session policy is missing; do not abandon registered actors')
            return
        host_policy(self.config)
        for file in sorted(self.state.glob('session-*.json')):
            try:
                private_file(file);record=json.loads(file.read_text());self._attach(record)
            except Exception as error:
                agent=file.stem.removeprefix('session-')
                self.records[agent]={'originRoomId':'unavailable','nativeThreadId':'unavailable',
                                     'state':'blocked','errorType':type(error).__name__}
                saved(self.state/('load-failure-'+agent+'.json'),self.records[agent])
        self.checkpoint()

    def attach(self,result):
        if self.closed:raise RuntimeError('Original host supervisor is closing')
        if result.get('state')!='ready' or result.get('sharedAppServer') is not True:
            raise ValueError('Accepted shared native bootstrap required')
        record={k:result[k] for k in ('agentId','originRoomId','nativeThreadId','sessionConfigPath','sessionConfigSha256')}
        file=self.state/('session-'+record['agentId']+'.json')
        if file.exists():
            old=json.loads(file.read_text())
            if any(old[k]!=v for k,v in record.items()):raise ValueError('Original resident agent binding changed')
            record=old
        else:
            self._validate(record)
            saved(file,record)
        self._attach(record)

    def _validate(self,record):
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
            p=Path(config[key]);expected=Path(policy['root'])/config['agentId']/('state' if key=='state' else 'work')
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
            finally:self.checkpoint()
        self.tasks[agent]=asyncio.create_task(run());self.checkpoint()

    async def close(self):
        self.closed=True
        for task in self.tasks.values():task.cancel()
        await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        self.checkpoint()
