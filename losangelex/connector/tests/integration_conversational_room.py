"""Actual room human fanout -> native peer question -> reply -> human result.

One host app-server, independent agent conversations, real PG/HTTP/SSE. No jobs,
placements or executor claims. Deliberate room publication is model-controlled.
"""
import asyncio,json,os,secrets,time
from pathlib import Path
from uuid import uuid4
from aiohttp import web,ClientSession
from hollywood_backbone.store import Store
from hollywood_backbone.server import application
from lax_connector.rpc import AppServer
from lax_connector.errors import HttpFailure
from lax_connector.room_input import submit_human,submit_peer,retain_peer
from lax_connector.room_tools import RoomTools,TOOLS
from lax_connector.room_runtime import RoomRuntime

async def main():
    os.umask(0o077);root=Path(os.environ['CONVERSATIONAL_ROOM_EVIDENCE']);root.mkdir(mode=0o700)
    cfg=json.load(open(os.environ['ROOM_NATIVE_ORIGINAL_CONFIG']));database=json.load(open(os.environ['ROOM_NATIVE_DATABASE']))
    uid=lambda:str(uuid4());authority,room=uid(),uid()
    credentials={k:{'principalId':uid(),'token':secrets.token_urlsafe(40)} for k in ('Owner','Global')}
    actors={k:{'id':uid(),'token':secrets.token_urlsafe(40)} for k in ('A','B')}
    marker='VERIFY'+secrets.token_hex(3).upper()
    tool_check=os.environ.get('ROOM_NATIVE_TOOL_CHECK')=='1'
    (root/'fixture.intent.private.json').write_text(json.dumps({'authority':authority,'room':room,'credentials':credentials,'actors':actors,'marker':marker}))
    store=Store(database);store.bootstrap(authority,'SYNTHETIC native collaborative room',{'globalRoomId':uid(),'credentials':credentials})
    owner=credentials['Owner']['principalId']
    for name,a in actors.items():store.principal(owner,a['id'],name,'agent',a['token'])
    store.create_room(owner,room,'Conversation QA','Synthetic native room collaboration',actors['A']['id'])
    store.membership(owner,room,actors['B']['id'],{'can_read':True,'can_post':True,'can_request':True},0)
    runner=web.AppRunner(application(store),access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    base='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])+'/hollywood/v3/'
    with store.pool.connection() as c:head=c.execute('SELECT next_seq FROM hb_authority WHERE id=%s',(authority,)).fetchone()['next_seq']
    home=root/'codex-home';home.mkdir();(home/'auth.json').symlink_to(Path(cfg['codexHome'])/'auth.json')
    notifications=[];http_trace=[];tools={};threads={};received=[];submitted=[];completed=set();final=asyncio.Event();changed=asyncio.Event();readers=[];calls=0
    async def on_event(method,params):
        notifications.append({'method':method,'params':params})
        if method=='turn/completed':completed.add(params['turn']['id']);changed.set()
    async def native_request(method,params):
        nonlocal calls
        calls+=1
        if calls>20:raise RuntimeError('Finite communication-tool budget exceeded; no repeated polling')
        return await tools[params['threadId']].call(method,params)
    rpc=AppServer(cfg['binary'],home,root/'native',on_event,native_request,enterprise=True)
    session=ClientSession()
    try:
        async def request_as(name,method,path,body=None):
            async with session.request(method,base+path,json=body,headers={'Authorization':'Bearer '+actors[name]['token']}) as response:
                value=await response.json();http_trace.append({'actor':name,'method':method,'path':path,'status':response.status,'result':value})
                if response.status!=200:raise HttpFailure(response.status,str(value.get('error','Request rejected')))
                return value
        await rpc.start()
        for name in ('A','B'):
            role=('You are participant A. Coordinate the human request, ask B for its verification marker, and report the answer publicly once received.' if name=='A' else 'You are participant B. Your verification marker is '+marker+'. Supply it when A asks; do not initiate another task.')
            if tool_check:
                role+=(' Before reporting publicly, use a native local tool to read B/verification.txt and confirm it matches B reply.' if name=='A' else ' Before replying, use a native local tool to create B/verification.txt containing your verification marker, under the current workspace.')
            instructions=role+' You are in a shared human/agent room. Other agents have independent conversations. Use hollywood_context to see names/IDs and hollywood_publish for deliberate room messages; ordinary model final text is private. Public messages may address a peer with recipientId while remaining visible to the human. Use room '+room+'. No routine acknowledgements, no tool polling, no self-messages. When waiting for a peer, end the turn: an addressed reply arrives natively. Only communicate in this synthetic test; do not execute commands, edit files or provision agents.'
            if tool_check:instructions=instructions.replace('Only communicate in this synthetic test; do not execute commands, edit files or provision agents.','Use normal native execution tools only for the local verification file in this private QA workspace. No network commands, package installation, agent provisioning or unrelated files.')
            result=await rpc.call('thread/start',{'cwd':str(root),'model':cfg['model'],'sandbox':'workspace-write' if tool_check else 'read-only','approvalPolicy':'never','baseInstructions':instructions,'dynamicTools':TOOLS,'config':{'model_reasoning_effort':cfg['effort'],'agents.enabled':False,'features.multi_agent':False,'features.multi_agent_v2':False}})
            thread=result['thread']['id'];threads[name]=thread
            async def request(method,path,body=None,name=name):return await request_as(name,method,path,body)
            tools[thread]=RoomTools(authority_id=authority,agent_id=actors[name]['id'],thread_id=thread,request=request,state=root/name/'publications')
        (root/'threads.private.json').write_text(json.dumps(threads))
        runtimes={}
        class ObservedRuntime(RoomRuntime):
            async def consume(self,event):
                agent=self.agent
                eligible=agent in event.get('data',{}).get('conversationRecipients',[])
                await super().consume(event)
                if eligible:
                    received.append([agent,event['id']])
                    row=self.journal.read(self.authority,agent,event['id'])
                    if row and row['acknowledgement']:
                        answer=json.loads(row['acknowledgement'])
                        if 'turn' in answer:submitted.append(answer['turn']['id']);changed.set()
                    if agent==actors['B']['id'] and event.get('author')==actors['A']['id'] and event.get('recipient')!=agent and marker in event.get('body',''):final.set()
        for name in actors:
            runtimes[name]=ObservedRuntime(rpc=rpc,session=session,base_url=base,token=actors[name]['token'],authority_id=authority,agent_id=actors[name]['id'],room_id=room,thread_id=threads[name],state=root/name/'receive',initial_cursor=head)
        readers=[asyncio.create_task(runtime.run()) for runtime in runtimes.values()]
        await asyncio.wait_for(asyncio.gather(*(runtime.ready.wait() for runtime in runtimes.values())),10)
        human=store.post(owner,room,'natural-human-request',{'kind':'message','audience':'room','body':'A, please ask B for its current verification marker and report it back here. B, answer A when asked. This is only a communication check; no other work.'})
        (root/'human.accepted.json').write_text(json.dumps(human))
        await asyncio.wait_for(final.wait(),180)
        async def settled():
            while not set(submitted)<=completed:
                changed.clear()
                if set(submitted)<=completed:break
                await changed.wait()
        await asyncio.wait_for(settled(),60)
        assert all([a['id'],human['event']['id']] in received for a in actors.values())
        posts=[entry for entry in http_trace if entry['method']=='POST'];assert any(p['actor']=='A' and p['result']['event'].get('recipient')==actors['B']['id'] for p in posts)
        assert any(p['actor']=='B' and p['result']['event'].get('recipient')==actors['A']['id'] and marker in p['result']['event']['body'] for p in posts)
        with store.pool.connection() as c:counts={table:c.execute('SELECT count(*) AS n FROM '+table+' WHERE authority=%s',(authority,)).fetchone()['n'] for table in ('hb_delivery','hb_executor')}
        assert counts=={'hb_delivery':0,'hb_executor':0}
        if tool_check:
            assert (root/'B'/'verification.txt').read_text().strip()==marker,'Native local tool did not create the verification artifact'
            commands=[n for n in notifications if n['method']=='item/completed' and n['params'].get('item',{}).get('type')=='commandExecution' and n['params']['item'].get('exitCode')==0]
            assert any(n['params'].get('threadId')==threads['B'] for n in commands),'B did not complete native execution'
            assert any(n['params'].get('threadId')==threads['A'] and marker in n['params']['item'].get('aggregatedOutput','') for n in commands),'A did not verify through native execution'
        result={'nativeLocalArtifactQualified':tool_check,'passed':True,'humanFanout':2,'nativeThreads':len(threads),'nativeTurns':len(set(submitted)),'model':cfg['model'],'effort':cfg['effort'],'agentRoomPosts':len(posts),'nativeCommunicationToolCalls':calls,'peerQuestionReplyAndPublicResult':True,'executionClaims':counts,'productionChanged':False,'durableRestartQualification':False}
        (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        for task in readers:task.cancel()
        await asyncio.gather(*readers,return_exceptions=True)
        for runtime in locals().get('runtimes',{}).values():runtime.close()
        await rpc.close();await session.close();await runner.cleanup();store.close()
        (root/'notifications.private.json').write_text(json.dumps(notifications));(root/'http.private.json').write_text(json.dumps(http_trace));(root/'received.private.json').write_text(json.dumps(received))
asyncio.run(main())
