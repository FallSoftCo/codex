"""Conversational mode of the existing lax-connect entrypoint.

One owned app-server and explicitly selected existing thread per agent. No room
message creates an executor, claims a delivery or changes model permissions.
Existing claimed-delivery installations remain on their original mode.
"""
import asyncio
import fcntl
import json
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout
from .journal import saved
from .rpc import AppServer
from .room_runtime import RoomRuntime
from .room_tools import RoomTools, TOOLS
from .errors import HttpFailure


class ConversationalAgent:
    def __init__(self,config):
        if config.get('runtimeMode')!='room-conversation':
            raise ValueError('Explicit room-conversation mode required')
        if any(k in config for k in ('homes','tokens','installedPurposeRuntime')):
            raise ValueError('Purpose-separated contexts require explicit adoption')
        self.config=config
        self.thread=config['nativeThreadId']
        if not self.thread or not config.get('rooms'):
            raise ValueError('Existing native thread and explicit room boundaries required')
        # Never erase saved client tools implicitly. The initial conversational
        # owner must attest to the declarations being installed at cold resume.
        if config.get('conversationDynamicTools')!=TOOLS:
            raise ValueError('Explicit reviewed conversational tool declarations required')
        self.state=Path(config['state']);self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=(self.state/'connector.lock').open('a')
        fcntl.flock(self.lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.session=None;self.tools=None;self.listeners=[]
        self.current_input=None;self.turn_sources={};self.native_items={};self.finished_turns=set()
        from .room_attention import RoomAttention
        self.attention=RoomAttention(self)
        self.rpc=AppServer(config['binary'],Path(config['codexHome']),self.state/'native',
                           self.event,self.tool,on_submission=self.attention.submitted,enterprise=True)

    async def http(self,method,path,payload=None):
        c=self.config
        headers={'Authorization':'Bearer '+c['token'],'X-Hollywood-Authority':c['authorityId'],
                 'X-Hollywood-Agent':c['agentId']}
        async with self.session.request(method,c['hollywoodUrl'].rstrip('/')+'/hollywood/v3/'+path,
                                        json=payload,headers=headers) as response:
            value=await response.json()
            if response.status!=200:
                raise HttpFailure(response.status,str(value.get('error','Request rejected')))
            return value

    async def status(self,value):
        saved(self.state/('room-'+value['roomId']+'-status.json'),value)

    async def before_native_input(self,event):
        if event.get('data',{}).get('authorKind') in ('human','agent'):self.current_input=event

    async def event(self,method,params):
        if params.get('threadId')!=self.thread:return
        if method=='turn/started' and self.current_input:
            self.turn_sources.setdefault(params['turn']['id'],self.current_input)
        if method=='item/started':self.native_items[params['item']['id']]=params['item']
        if method=='item/completed':self.native_items.pop(params['item']['id'],None)
        if method=='turn/completed':
            turn=params['turn']['id'];self.finished_turns.add(turn)
            await self.attention.finish(turn)
            self.turn_sources.pop(turn,None)
            if len(self.finished_turns)>1024:self.finished_turns={turn}
        # Actual native state, independent of room-message/delivery state. Full
        # activity/attention projection is integrated separately, not chat spam.
        if method in ('turn/started','turn/completed','error'):
            saved(self.state/'conversation-native-status.json',{'method':method,'params':params})

    async def tool(self,method,params):
        if method=='item/tool/call' and params.get('tool') in {t['name'] for t in TOOLS}:
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
            self.tools=RoomTools(authority_id=self.config['authorityId'],agent_id=self.config['agentId'],
                                 thread_id=self.thread,request=self.http,state=self.state/'publications')
            cold_start=self.rpc.process is None
            if cold_start:
                await self.rpc.start()
            elif self.rpc.process.returncode is not None:
                raise RuntimeError('Original native transport stopped; no implicit replacement')
            # No thread/start, sampling, model/permission override or history copy.
            if cold_start:
                result=await self.rpc.call('thread/resume',{'threadId':self.thread,'excludeTurns':True,
                              'dynamicTools':self.config['conversationDynamicTools'],
                              'config':{'features.default_mode_request_user_input':True}})
                if result['thread']['id']!=self.thread:
                    raise ValueError('Native resume selected a different conversation')
            else:
                loaded=await self.rpc.call('thread/loaded/list',{'limit':100})
                if self.thread not in loaded['data']:
                    raise ValueError('Selected conversation is not on the original transport')
            saved(self.state/'conversation-resume.json',{'threadId':self.thread,'resumed':cold_start,'attachedLoaded':not cold_start})
            for room in self.config['rooms']:
                listener=RoomRuntime(rpc=self.rpc,session=self.session,
                    base_url=self.config['hollywoodUrl'].rstrip('/')+'/hollywood/v3/',
                    token=self.config['token'],authority_id=self.config['authorityId'],agent_id=self.config['agentId'],
                    room_id=room['roomId'],thread_id=self.thread,state=self.state/'rooms'/room['roomId'],
                    initial_cursor=room['after'],on_status=self.status,route_headers={'X-Hollywood-Authority':self.config['authorityId'],'X-Hollywood-Agent':self.config['agentId']},on_room_event=self.attention.observe,before_native_input=self.before_native_input)
                self.listeners.append(listener);tasks.append(asyncio.create_task(listener.run()))
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:task.result()
            raise RuntimeError('Room input stopped; inspect room status before continuation')
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            for listener in self.listeners:listener.close()
            await self.rpc.close();await self.session.close()
            self.lock.close()
