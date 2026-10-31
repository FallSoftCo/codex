"""One real native daemon, two clients, concurrent callbacks and scoped stop.

The Responses transport is an owned local synthetic HTTP fixture. No real
provider/account is used, and no production process or conversation is touched.
"""
import asyncio
import json
import os
import signal
import time
from pathlib import Path
from uuid import uuid4
from aiohttp import web
from lax_connector.rpc_shared import SharedAppServer

async def main():
    os.umask(0o077)
    root=Path(os.environ['SHARED_NATIVE_EVIDENCE']);root.mkdir(mode=0o700)
    home=root/'profile';home.mkdir(mode=0o700)
    requests=[];callbacks={'A':[],'B':[]};events={'A':[],'B':[]};waiting=asyncio.Event();release=asyncio.Event();completed={'A':asyncio.Queue(),'B':asyncio.Queue()}
    async def respond(request):
        body=await request.json();requests.append(body)
        raw=json.dumps(body.get('input',[]));who='A' if 'ROOM_A' in raw else 'B'
        output=any(item.get('type')=='function_call_output' for item in body.get('input',[]))
        if output:
            item={'type':'message','role':'assistant','id':'answer_'+str(len(requests)),'content':[{'type':'output_text','text':'RESULT_ROOM_'+who}]}
        else:
            item={'type':'function_call','call_id':'callback_'+who,'name':'hollywood_probe','arguments':json.dumps({'marker':'ROOM_'+who})}
        response_id='owned_'+str(len(requests));data=[{'type':'response.created','response':{'id':response_id}},{'type':'response.output_item.done','item':item},{'type':'response.completed','response':{'id':response_id,'usage':{'input_tokens':0,'input_tokens_details':None,'output_tokens':0,'output_tokens_details':None,'total_tokens':0}}}]
        return web.Response(text=''.join('data: '+json.dumps(v)+'\n\n' for v in data),content_type='text/event-stream')
    app=web.Application(client_max_size=16*1024**2);app.router.add_post('/v1/responses',respond);runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
    (home/'config.toml').write_text('model_provider="fixture"\nmodel="gpt-6.1-sol"\n[model_providers.fixture]\nname="Owned synthetic provider"\nbase_url="http://127.0.0.1:'+str(port)+'/v1"\nwire_api="responses"\nrequires_openai_auth=false\n[features]\ncode_mode=false\n')
    binary=os.environ['SHARED_NATIVE_BINARY'];socket=root/'native.sock';authority=str(uuid4());host=str(uuid4())
    manifest={'schema':'lax-native-host/v1','runtimeMode':'room-conversation','authorityId':authority,'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root/'native'),'socket':str(socket)};(root/'host.json').write_text(json.dumps(manifest))
    env=dict(os.environ,CODEX_HOME=str(home),LAX_NATIVE_ENTERPRISE='1',LAX_NATIVE_RUNTIME_MODE='room-conversation');env.pop('LAX_CANONICAL_NATIVE_CHANNEL',None)
    log=(root/'native.log').open('xb');process=await asyncio.create_subprocess_exec(binary,'--listen','unix://'+str(socket),'-c','check_for_update_on_startup=false',env=env,stdout=log,stderr=log,start_new_session=True);log.close();clients=[]
    async def notify(who,method,params):
        events[who].append({'method':method,'params':params})
        if method=='turn/completed':await completed[who].put(params)
    async def callback(who,method,params):
        callbacks[who].append({'method':method,'params':params})
        assert method=='item/tool/call',method
        assert params['tool']=='hollywood_probe'
        args=params['arguments'];args=json.loads(args) if isinstance(args,str) else args
        assert args=={'marker':'ROOM_'+who},args
        if who=='A':waiting.set();await release.wait()
        return {'success':True,'contentItems':[{'type':'inputText','text':'RESULT_ROOM_'+who}]}
    def client(who,thread=None):
        config={'authorityId':authority,'hostId':host,'binary':binary,'codexHome':str(home),'state':str(root/('agent-'+who)),'nativeThreadId':thread,'nativeServer':{'manifest':str(root/'host.json')}}
        return SharedAppServer(config,lambda m,p:notify(who,m,p),lambda m,p:callback(who,m,p))
    try:
        for _ in range(150):
            if process.returncode is not None:raise RuntimeError('Native daemon exited before connection')
            if socket.exists():break
            await asyncio.sleep(.1)
        a,b=client('A'),client('B');clients=[a,b];await asyncio.gather(a.start(),b.start())
        tool={'name':'hollywood_probe','description':'Owned synthetic scoped callback','inputSchema':{'type':'object','properties':{'marker':{'type':'string'}},'required':['marker'],'additionalProperties':False}}
        params={'cwd':str(root),'model':'gpt-6.1-sol','modelProvider':'fixture','sandbox':'danger-full-access','approvalPolicy':'never','dynamicTools':[tool],'config':{'features.code_mode':False}}
        ra,rb=await asyncio.gather(a.call('thread/start',params),b.call('thread/start',params));ta=ra['thread']['id'];tb=rb['thread']['id'];assert ta!=tb
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
        c=client('A',ta);clients.append(c);await c.start();resumed=await c.call('thread/resume',{'threadId':ta,'excludeTurns':True,'dynamicTools':[tool]});assert resumed['thread']['id']==ta
        changed=dict(tool,description='Changed binding must be rejected')
        try:await c.call('thread/resume',{'threadId':ta,'excludeTurns':True,'dynamicTools':[changed]})
        except Exception as error:assert 'cannot replace dynamic tools' in str(error)
        else:raise AssertionError('Loaded tool replacement was accepted')
        assert all(v['params'].get('threadId')==ta for v in callbacks['A']);assert all(v['params'].get('threadId')==tb for v in callbacks['B']);assert len(callbacks['A'])==1 and len(callbacks['B'])==1
        assert any('RESULT_ROOM_B' in json.dumps(v) for v in events['B'])
        result={'state':'passed','nativeServerPid':process.pid,'separateThreads':[ta,tb],'callbackOwnersVerified':True,'heldAWhileBCompleted':True,'interruptAWithoutStoppingB':True,'disconnectAWithoutStoppingDaemon':True,'BNextTurnCompleted':True,'reconnectOriginalA':True,'identicalLoadedToolAttachmentAccepted':True,'differentLoadedToolsRejected':True,'crossThreadConnectorCallRejected':True,'localSyntheticProviderRequests':len(requests),'realProviderCalls':0,'productionChanged':False};(root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
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
