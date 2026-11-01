"""One real native daemon, two clients, concurrent callbacks and scoped stop.

The Responses transport is an owned local synthetic HTTP fixture. No real
provider/account is used, and no production process or conversation is touched.
"""
import asyncio
import json
import hashlib
import os
import signal
import re
import time
from pathlib import Path
from uuid import uuid4
from aiohttp import web
from lax_connector.rpc_shared import SharedAppServer
from lax_connector.room_tools import RoomTools,TOOLS

async def main():
    os.umask(0o077)
    root=Path(os.environ['SHARED_NATIVE_EVIDENCE']);root.mkdir(mode=0o700)
    home=root/'profile';home.mkdir(mode=0o700)
    authority,host,room=[str(uuid4()) for _ in range(3)]
    agents={who:str(uuid4()) for who in ('A','B')};handlers={};messages=[]
    for who in agents:
        (root/('agent-'+who)/'work').mkdir(parents=True,mode=0o700)
    requests=[];callbacks={'A':[],'B':[]};events={'A':[],'B':[]};waiting=asyncio.Event();release=asyncio.Event();completed={'A':asyncio.Queue(),'B':asyncio.Queue()}
    async def respond(request):
        body=await request.json();requests.append(body)
        user=json.dumps([x for x in body.get('input',[]) if x.get('role')=='user'])
        marker=re.findall(r'ROOM_[AB](?:_AGAIN|_RECONNECT)?',user)[-1]
        who=marker[5];call='callback_'+marker
        output=any(item.get('type')=='function_call_output' and item.get('call_id')==call for item in body.get('input',[]))
        if output:
            item={'type':'message','role':'assistant','id':'answer_'+str(len(requests)),'content':[{'type':'output_text','text':'RESULT_ROOM_'+who}]}
        else:
            item={'type':'function_call','call_id':call,'name':'hollywood_publish','arguments':json.dumps({'roomId':room,'body':marker,'audience':'room','recipientId':agents['B' if who=='A' else 'A'],'responsePhase':'message'})}
        response_id='owned_'+str(len(requests));data=[{'type':'response.created','response':{'id':response_id}},{'type':'response.output_item.done','item':item},{'type':'response.completed','response':{'id':response_id,'usage':{'input_tokens':0,'input_tokens_details':None,'output_tokens':0,'output_tokens_details':None,'total_tokens':0}}}]
        return web.Response(text=''.join('data: '+json.dumps(v)+'\n\n' for v in data),content_type='text/event-stream')
    app=web.Application(client_max_size=16*1024**2);app.router.add_post('/v1/responses',respond);runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
    (home/'config.toml').write_text('model_provider="fixture"\nmodel="gpt-6.1-sol"\n[model_providers.fixture]\nname="Owned synthetic provider"\nbase_url="http://127.0.0.1:'+str(port)+'/v1"\nwire_api="responses"\nrequires_openai_auth=false\n[features]\ncode_mode=false\n')
    binary=os.environ['SHARED_NATIVE_BINARY'];socket=root/'native.sock'
    manifest={'schema':'lax-native-host/v1','runtimeMode':'room-conversation','authorityId':authority,'hostId':host,'ownerAgentId':agents['A'],'binary':binary,'codexHome':str(home),'state':str(root/'native'),'socket':str(socket)};(root/'host.json').write_text(json.dumps(manifest))
    (root/'tmp').mkdir(mode=0o700)
    env={'PATH':'/usr/bin:/bin','HOME':str(home),'CODEX_HOME':str(home),'TMPDIR':str(root/'tmp'),
         'LAX_NATIVE_ENTERPRISE':'1','LAX_NATIVE_RUNTIME_MODE':'room-conversation','OMP_NUM_THREADS':'2'}
    log=(root/'native.log').open('xb');process=await asyncio.create_subprocess_exec(binary,'--listen','unix://'+str(socket),'-c','check_for_update_on_startup=false',env=env,stdout=log,stderr=log,start_new_session=True);log.close();clients=[]
    startticks=Path('/proc',str(process.pid),'stat').read_text().rsplit(')',1)[1].split()[19]
    native_image=Path('/proc',str(process.pid),'exe').stat()
    async def notify(who,method,params):
        events[who].append({'method':method,'params':params})
        if method=='turn/completed':await completed[who].put(params)
    async def callback(who,method,params):
        callbacks[who].append({'method':method,'params':params})
        assert method=='item/tool/call',method
        assert params['tool']=='hollywood_publish'
        args=params['arguments'];args=json.loads(args) if isinstance(args,str) else args
        assert args['roomId']==room and args['body'].startswith('ROOM_'+who),args
        if who=='A' and len(callbacks['A'])==1:
            waiting.set();await release.wait()
            return {'success':True,'contentItems':[{'type':'inputText','text':'Interrupted synthetic callback; no publication'}]}
        return await handlers[who].call(method,params)
    def client(who,thread=None):
        config={'authorityId':authority,'agentId':agents[who],'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root/('agent-'+who)),'nativeThreadId':thread,'nativeServer':{'manifest':str(root/'host.json')}}
        return SharedAppServer(config,lambda m,p:notify(who,m,p),lambda m,p:callback(who,m,p))
    def request(who):
        async def accepted(method,path,payload):
            assert method=='POST' and path=='rooms/'+room+'/messages'
            event={'id':str(uuid4()),'authority':authority,'author':agents[who],'room':room,
                   'kind':'message','body':payload['body'],'audience':payload['audience'],
                   'recipient':payload['recipientId'],'source':payload.get('sourceEventId'),
                   'data':{'responsePhase':payload['responsePhase']}}
            messages.append({'agent':who,'operationId':payload['operationId'],'event':event})
            return {'accepted':True,'event':event,'deliveries':[]}
        return accepted
    try:
        for _ in range(150):
            if process.returncode is not None:raise RuntimeError('Native daemon exited before connection')
            if socket.exists():break
            await asyncio.sleep(.1)
        a,b=client('A'),client('B');clients=[a,b];await asyncio.gather(a.start(),b.start())
        tool=next(x for x in TOOLS if x['name']=='hollywood_publish')
        params={'cwd':str(root),'model':'gpt-6.1-sol','modelProvider':'fixture','sandbox':'danger-full-access','approvalPolicy':'never','dynamicTools':TOOLS,'config':{'features.code_mode':False}}
        ra,rb=await asyncio.gather(a.call('thread/start',{**params,'cwd':str(root/'agent-A/work')}),b.call('thread/start',{**params,'cwd':str(root/'agent-B/work')}));ta=ra['thread']['id'];tb=rb['thread']['id'];assert ta!=tb
        for who,thread in [('A',ta),('B',tb)]:
            handlers[who]=RoomTools(authority_id=authority,agent_id=agents[who],thread_id=thread,request=request(who),state=root/('agent-'+who)/'message-receipts')
        # A connector cannot retarget another actor's thread, even though these
        # local clients intentionally share one trusted native account profile.
        try:await a.call('thread/read',{'threadId':tb,'includeTurns':False})
        except ValueError:pass
        else:raise AssertionError('Cross-agent call was not rejected')
        turns=await asyncio.gather(a.call('turn/start',{'threadId':ta,'input':[{'type':'text','text':'ROOM_A'}]}),b.call('turn/start',{'threadId':tb,'input':[{'type':'text','text':'ROOM_B'}]}));turna=turns[0]['turn']['id']
        await asyncio.wait_for(waiting.wait(),30);done_b=await asyncio.wait_for(completed['B'].get(),30);assert done_b['turn']['status']=='completed',done_b
        assert completed['A'].empty(),'Held A callback must not complete before its own response'
        await a.call('turn/interrupt',{'threadId':ta,'turnId':turna});done_a=await asyncio.wait_for(completed['A'].get(),30);assert done_a['turn']['status']=='interrupted',done_a
        release.set();await a.close();clients.remove(a);assert process.returncode is None
        again=await b.call('turn/start',{'threadId':tb,'input':[{'type':'text','text':'ROOM_B_AGAIN'}]});again_done=await asyncio.wait_for(completed['B'].get(),30);assert again_done['turn']['id']==again['turn']['id'] and again_done['turn']['status']=='completed'
        from lax_connector.transport_adoption import inspect
        config_file=root/'inspect-b.json'
        config_file.write_text(json.dumps({'runtimeMode':'room-conversation','authorityId':authority,'agentId':agents['B'],'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root/'agent-B'),'nativeThreadId':tb,'nativeServer':{'manifest':str(root/'host.json')}}))
        read=await inspect(str(config_file),str(root/'host.json'),existing_client=True)
        assert read['nativeThreadId']==tb and read['otherLoadedThreadsPreserved']==1
        try:await inspect(str(config_file),str(root/'host.json'))
        except ValueError as error:assert 'coordinated owner drainage' in str(error)
        else:raise AssertionError('Original adoption drainage guard weakened')
        c=client('A',ta);clients.append(c);await c.start();resumed=await c.call('thread/resume',{'threadId':ta,'excludeTurns':True,'dynamicTools':TOOLS});assert resumed['thread']['id']==ta
        await c.call('turn/start',{'threadId':ta,'input':[{'type':'text','text':'ROOM_A_RECONNECT'}]})
        reconnect_done=await asyncio.wait_for(completed['A'].get(),30)
        assert reconnect_done['turn']['status']=='completed'
        changed=dict(tool,description='Changed binding must be rejected')
        try:await c.call('thread/resume',{'threadId':ta,'excludeTurns':True,'dynamicTools':[changed if x['name']==tool['name'] else x for x in TOOLS]})
        except Exception as error:assert 'cannot replace dynamic tools' in str(error)
        else:raise AssertionError('Loaded tool replacement was accepted')
        assert all(v['params'].get('threadId')==ta for v in callbacks['A']);assert all(v['params'].get('threadId')==tb for v in callbacks['B']);assert len(callbacks['A'])==2 and len(callbacks['B'])==2
        assert len(messages)==3 and len({v['operationId'] for v in messages})==3
        assert all(v['event']['author']==agents[v['agent']] and v['event']['body'].startswith('ROOM_'+v['agent']) for v in messages)
        assert messages[-1]['event']['author']==agents['A'] and messages[-1]['event']['body']=='ROOM_A_RECONNECT'
        assert Path('/proc',str(process.pid),'stat').read_text().rsplit(')',1)[1].split()[19]==startticks
        current_image=Path('/proc',str(process.pid),'exe').stat()
        assert (current_image.st_dev,current_image.st_ino)==(native_image.st_dev,native_image.st_ino)
        assert any('RESULT_ROOM_B' in json.dumps(v) for v in events['B'])
        result={'state':'passed','nativeServerPid':process.pid,'nativeStartTicks':startticks,'logicalAgents':agents,'separateThreads':[ta,tb],'separateWorkspaces':True,'loadedNativeToolCount':len(TOOLS),'nativeToolsSha256':hashlib.sha256(json.dumps(TOOLS,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'callbackOwnersVerified':True,'actualRoomToolsPublicationReceipts':messages,'heldAWhileBCompleted':True,'interruptAWithoutStoppingB':True,'disconnectAWithoutStoppingDaemon':True,'BNextTurnCompleted':True,'reconnectOriginalA':True,'reconnectedAPublishedAsA':True,'existingClientInspectionPreservedOtherThread':read,'oldAdoptionDrainageGuardRetained':True,'identicalLoadedToolAttachmentAccepted':True,'differentLoadedToolsRejected':True,'crossThreadConnectorCallRejected':True,'localSyntheticProviderRequests':len(requests),'realProviderCalls':0,'syntheticHollywoodOnly':True,'productionChanged':False};(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        release.set()
        for c in clients:
            try:await c.close()
            except Exception:pass
        if process.returncode is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:await asyncio.wait_for(process.wait(),15)
            except asyncio.TimeoutError:os.killpg(process.pid,signal.SIGKILL);await process.wait()
        (root/'requests.json').write_text(json.dumps(requests));(root/'callbacks.json').write_text(json.dumps(callbacks));(root/'events.json').write_text(json.dumps(events));await runner.cleanup()
asyncio.run(main())
