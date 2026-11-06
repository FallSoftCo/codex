"""Conversational mode of the existing lax-connect entrypoint.

One owned app-server and explicitly selected existing thread per agent. No room
message creates an executor, claims a delivery or changes model permissions.
Existing claimed-delivery installations remain on their original mode.
"""
from .runtime_files import state_directory
import asyncio
from .runtime_files import exclusive_lock
import hashlib
import json
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout
from .journal import saved
from .rpc_shared import native_client
from .room_runtime import RoomRuntime
from .room_tools import RoomTools, TOOLS
from .errors import HttpFailure
from .room_permissions import observed


class ConversationalAgent:
    def __init__(self,config):
        if config.get('runtimeMode')!='room-conversation':
            raise ValueError('Explicit room-conversation mode required')
        if any(k in config for k in ('homes','tokens','installedPurposeRuntime')):
            raise ValueError('Purpose-separated contexts require explicit adoption')
        self.config=config
        self.thread=config['nativeThreadId']
        from .room_participation import resume_overrides
        self.resume_instructions, self.participation_adoption = resume_overrides(config)
        if not self.thread or not config.get('rooms'):
            raise ValueError('Existing native thread and explicit room boundaries required')
        # Never erase saved client tools implicitly. The initial conversational
        # owner must attest to the declarations being installed at cold resume.
        from .room_inspect import READ_NAMES
        legacy_tools=[tool for tool in TOOLS if tool['name'] not in READ_NAMES]
        from .room_resume import supported_declarations
        from .project_tools import PROJECT_TOOLS
        selected_tools=TOOLS+PROJECT_TOOLS if config.get('projectCommunication') else TOOLS
        if not supported_declarations(config.get('conversationDynamicTools'),selected_tools,legacy_tools if not config.get('projectCommunication') else selected_tools):
            raise ValueError('Explicit reviewed conversational tool declarations required')
        self.state=Path(config['state']);state_directory(self.state, parents=True,exist_ok=True)
        self.lock=(self.state/'connector.lock').open('a')
        exclusive_lock(self.lock)
        self.session=None;self.tools=None;self.subscriptions=None
        self.current_input=None;self.native_active_turn=None;self.source_events={};self.turn_sources={};self.turn_input_rooms={};self.native_items={};self.finished_turns=set()
        from .room_attention import RoomAttention
        self.attention=RoomAttention(self)
        from .room_activity import RoomActivity
        self.activity=RoomActivity(state=self.state/'room-activity',thread=self.thread,agent=config['agentId'],send=self.http)
        from .room_native_state import RoomNativeState
        self.native_state=RoomNativeState(state=self.state/'native-observations',thread=self.thread,agent=config['agentId'],rooms=config['rooms'],send=self.http,authority=config['authorityId'],project=config.get('projectCommunication'))
        from .conversation_io import ConversationIO
        self.conversation_io=ConversationIO(self.state/'conversation-io.sqlite',authority=config['authorityId'],agent=config['agentId'],thread=self.thread)
        self.output=None
        from .project_runtime import ProjectRuntime
        self.project=ProjectRuntime(self,config['projectCommunication']) if config.get('projectCommunication') else None
        self.origin_control=None
        self.session_supervisor=None
        self.host_supervisor=None
        self.rpc=native_client(config,self.event,self.tool,on_submission=self.attention.submitted)

    @property
    def listeners(self):
        return [value[0] for value in self.subscriptions.live.values()] if self.subscriptions else []

    async def http(self,method,path,payload=None):
        c=self.config
        headers={'Authorization':'Bearer '+c['token'],'X-Hollywood-Authority':c['authorityId'],
                 'X-Hollywood-Agent':c['agentId']}
        async with self.session.request(method,c['hollywoodUrl'].rstrip('/')+'/hollywood/v3/'+path,
                                        json=payload,headers=headers,timeout=ClientTimeout(total=30,sock_connect=10,sock_read=25)) as response:
            value=await response.json()
            if response.status!=200:
                raise HttpFailure(response.status,str(value.get('error','Request rejected')),
                                  code=value.get('error'),may_apply=value.get('mayApply'))
            return value

    async def status(self,value):
        if self.session_supervisor:self.session_supervisor.checkpoint()
        if self.subscriptions:self.subscriptions.note(value)
        saved(self.state/('room-'+value['roomId']+'-status.json'),value)

    async def before_native_input(self,event):
        self.conversation_io.stage(event)
        if event.get('data',{}).get('authorKind')=='human':self.source_events[event['id']]=event

    async def observe_room_event(self,event):
        # Runs before conversationRecipients filtering. Own replies are visible
        # on the canonical feed but must never become another native input.
        if self.conversation_io.observe_own_reply(event) and self.output:
            self.output.wake.set()  # transport only, never starts a model turn
        await self.attention.observe(event)

    async def native_receipt(self,event,reply):
        turn=self.conversation_io.bind(event,reply)
        if self.project:self.project.admitted(event,turn)
        source=self.project.causal_source(event,turn) if self.project else self.conversation_io.primary(turn)
        self.turn_sources[turn]=source
        self.turn_input_rooms[turn]=self.conversation_io.rooms(turn)
        if self.native_active_turn==turn:self.native_state.update(self.native_state.status,source)
        if self.output:self.output.wake.set()

    async def event(self,method,params):
        if params.get('threadId')!=self.thread:return
        if method=='hollywood/runtimeLost':
            self.native_state.update({'type':'unavailable','activeFlags':[]},self.turn_sources.get(self.native_active_turn))
            return
        if method=='thread/status/changed':self.native_state.update(params['status'],self.turn_sources.get(self.native_active_turn))
        if method=='turn/started':
            self.native_active_turn=params['turn']['id']
            # The input ACK may precede this notification. Bind the status
            # source now too; keep the exact native status and active flags.
            self.native_state.update(self.native_state.status,self.turn_sources.get(self.native_active_turn))
        self.activity.record(method,params,self.turn_sources.get(params.get('turnId')))
        if method=='item/started':self.native_items[params['item']['id']]=params['item']
        if method=='item/completed':
            item=params['item'];self.native_items.pop(item['id'],None)
            if self.project:self.project.ledger.evidence.native_command(params['turnId'],item)
            if item.get('type')=='agentMessage' and item.get('phase') in (None,'final_answer'):
                self.conversation_io.final(params['turnId'],item['id'],item.get('text',''))
                if self.output:self.output.wake.set()
            if item.get('type')=='userMessage':
                source=self.source_events.pop(item.get('clientId'),None)
                if source:
                    self.turn_sources[params['turnId']]=source
                    self.turn_input_rooms.setdefault(params['turnId'],set()).add(source['room'])
                    if self.native_active_turn==params['turnId']:self.native_state.update(self.native_state.status,source)
        if method=='turn/completed':
            turn=params['turn']['id'];self.finished_turns.add(turn)
            self.conversation_io.ended(turn,params['turn'].get('status','completed'))
            if self.project:self.project.ended(turn,params['turn'].get('status','completed'),params['turn'].get('error'))
            if self.output:self.output.wake.set()
            await self.attention.finish(turn)
            self.turn_sources.pop(turn,None)
            self.turn_input_rooms.pop(turn,None)
            if self.native_active_turn==turn:
                self.native_active_turn=None
                if self.native_state.status['type']=='idle':self.native_state.update(self.native_state.status,None)
            if len(self.finished_turns)>1024:self.finished_turns={turn}
        # Actual native state, independent of room-message/delivery state. Full
        # activity/attention projection is integrated separately, not chat spam.
        if method in ('turn/started','turn/completed','error'):
            saved(self.state/'conversation-native-status.json',{'method':method,'params':params})

        if self.host_supervisor:self.host_supervisor.checkpoint()

    async def tool(self,method,params):
        if method=='item/tool/call' and params.get('tool') in {t['name'] for t in self.config['conversationDynamicTools']}:
            return await self.tools.call(method,params)
        from .room_attention import QUESTION, APPROVAL
        if method in QUESTION|APPROVAL:return await self.attention.wait(method,params)
        # Never fabricate a question answer or execution approval. Preserve the
        # exact callback as an explicit integration blocker until it is wired.
        saved(self.state/'unsupported-native-callback.json',{'method':method,'params':params})
        raise RuntimeError('Native callback requires its supported handler: '+method)

    async def serve(self):
        self.session=ClientSession(timeout=ClientTimeout(total=None,sock_connect=15))
        tasks=[]
        try:
            if not self.config.get('originRoomId'):
                from .room_parent_startup import emit
                emit(self.config)
                from .room_session_supervisor import RoomSessionSupervisor
                self.session_supervisor=RoomSessionSupervisor(self)
                self.session_supervisor.load()
            self.tools=RoomTools(authority_id=self.config['authorityId'],agent_id=self.config['agentId'],
                                 thread_id=self.thread,request=self.http,state=self.state/'publications',
                                 source_for_turn=lambda turn:self.turn_sources.get(turn,{}).get('id'),host_config=self.config,
                                 on_membership=lambda:self.subscriptions.wake.set() if self.subscriptions else None,
                                 conversation_io=self.conversation_io,native_state_view=self.native_state.own_view,session_supervisor=self.session_supervisor)
            if self.project:
                await self.project.verify()
                self.tools.project=self.project
            from .room_reply_window import ReplyWindow
            def reviewed(turn,source):
                self.turn_sources.setdefault(turn,source)
                self.turn_input_rooms.setdefault(turn,set()).add(source['room'])
            if not self.project:
                self.tools.reply_window=ReplyWindow(self.conversation_io,self.rpc,
                    idle=lambda:self.native_active_turn is None,on_review=reviewed)
            self.conversation_io.reply_window=self.tools.reply_window
            from .room_output import RoomOutput
            self.output=RoomOutput(self.conversation_io,self.tools)
            if (self.rpc.home.resolve()!=Path(self.config['codexHome']).resolve()
                    or not self.rpc.shared and self.rpc.state.resolve()!=(self.state/'native').resolve()):
                raise ValueError('Native transport must retain the original agent profile and database')
            cold_start=not self.rpc.has_started
            if cold_start:
                await self.rpc.start()
            elif not self.rpc.is_connected:
                raise RuntimeError('Original native transport stopped; no implicit replacement')
            # No thread/start, sampling, model/permission override or history copy.
            instruction_adoption = None
            if cold_start:
                if self.participation_adoption:
                    from .room_instruction_adoption import InstructionAdoption
                    instruction_adoption = InstructionAdoption(self.config, self.rpc, self.resume_instructions)
                    active_overrides = await instruction_adoption.begin()
                else:
                    active_overrides = self.resume_instructions
                resume={'threadId':self.thread,'excludeTurns':True,
                        'config':{'features.default_mode_request_user_input':True},**active_overrides}
                # Bind the exact accepted tools across warm and cold transport startup.
                from .room_resume import resume_configured
                result,tool_binding=await resume_configured(self.rpc,resume,self.config['conversationDynamicTools'],
                    reviewed_instructions=self.resume_instructions if self.project else None)
                effective_permissions=observed(result)
                self.native_state.update(result['thread'].get('status',{'type':'unavailable','activeFlags':[]}),None)
                if result['thread']['id']!=self.thread:
                    raise ValueError('Native resume selected a different conversation')
            else:
                if self.resume_instructions:raise ValueError('Instruction adoption requires a cold resume, never active-thread injection')
                loaded=await self.rpc.call('thread/loaded/list',{'limit':100})
                if self.thread not in loaded['data']:
                    raise ValueError('Selected conversation is not on the original transport')
            resume_receipt = {'threadId':self.thread,'resumed':cold_start,'attachedLoaded':not cold_start,
                'effectivePermissions':effective_permissions if cold_start else None,
                'nativeToolBinding':tool_binding if cold_start else None,
                'instructionOverridesSha256':hashlib.sha256(json.dumps(self.resume_instructions,sort_keys=True,
                    **({'separators':(',',':')} if instruction_adoption else {})).encode()).hexdigest() if self.resume_instructions else None,
                'participationPolicy':self.participation_adoption,
                **(instruction_adoption.receipt_fields() if instruction_adoption else {})}
            saved(self.state/'conversation-resume.json',resume_receipt)
            if instruction_adoption:instruction_adoption.complete(resume_receipt)
            # Reconcile only finals already captured locally before a connection
            # ended. This is one bounded metadata read, not model polling.
            unfinished=set(self.conversation_io.unfinished())
            if self.project:unfinished.update(r['turn'] for r in self.project.ledger.db.execute("SELECT DISTINCT t.turn FROM turn_work t JOIN work w ON w.id=t.work WHERE w.state='working' AND NOT EXISTS(SELECT 1 FROM native_end n WHERE n.turn=t.turn)"))
            if unfinished:
                try:
                    page=await self.rpc.call('thread/turns/list',{'threadId':self.thread,'limit':100,'sortDirection':'desc','itemsView':'summary'})
                    for turn in page['data']:
                        if turn['id'] in unfinished and turn['status'] in ('completed','failed','interrupted'):
                            self.conversation_io.ended(turn['id'],turn['status'])
                            if self.project:self.project.ended(turn['id'],turn['status'],turn.get('error'))
                except Exception as error:
                    saved(self.state/'output-reconciliation-unavailable.json',{'error':type(error).__name__,'turns':sorted(unfinished)})
            self.output.start()
            if self.project:
                self.project.start()
                tasks.append(self.project.task)
            self.activity.start()
            self.native_state.start()
            def create(room,after):
                return RoomRuntime(rpc=self.rpc,session=self.session,
                    base_url=self.config['hollywoodUrl'].rstrip('/')+'/hollywood/v3/',
                    token=self.config['token'],authority_id=self.config['authorityId'],agent_id=self.config['agentId'],
                    room_id=room,thread_id=self.thread,state=self.state/'rooms'/room,
                    initial_cursor=after,on_status=self.status,route_headers={'X-Hollywood-Authority':self.config['authorityId'],'X-Hollywood-Agent':self.config['agentId']},on_room_event=self.observe_room_event,before_native_input=self.before_native_input,on_native_receipt=self.native_receipt,project_mode=bool(self.project),on_input_candidate=self.project.candidate if self.project else None)
            def room_set(rooms):self.native_state.set_rooms(rooms)
            from .room_subscriptions import RoomSubscriptions
            from .room_origin_control import RoomOriginControl
            if self.session_supervisor:
                self.origin_control=RoomOriginControl(config=self.config, request=self.http,
                    thread=self.thread, state=self.state/'room-origin-control',session_supervisor=self.session_supervisor)
            self.subscriptions=RoomSubscriptions(state=self.state/'subscriptions',authority=self.config['authorityId'],
                agent=self.config['agentId'],thread=self.thread,rooms=self.config['rooms'],request=self.http,create=create,on_rooms=room_set,
                on_catalog=self.origin_control.observe if self.origin_control else None)
            tasks.append(asyncio.create_task(self.subscriptions.run()))
            tasks.append(asyncio.create_task(self.rpc.wait_closed()))
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
            raise RuntimeError('Native process or room subscription owner stopped; inspect original state')
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if self.subscriptions:await self.subscriptions.close()
            if self.origin_control:await self.origin_control.close()
            if self.session_supervisor:await self.session_supervisor.close()
            await self.native_state.close()
            await self.activity.close()
            if self.output:await self.output.close()
            if self.project:await self.project.close()
            self.conversation_io.close()
            await self.rpc.close();await self.session.close()
            self.lock.close()
