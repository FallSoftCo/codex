"""Actual native role bindings survive a loaded reconnect and cold reload.

Isolated empty profile, no account, provider call or Hollywood business event.
The original tools are deliberately different from the later reviewed role.
"""
import asyncio,json,os,signal
from pathlib import Path
from uuid import uuid4
from lax_connector.rpc_shared import SharedAppServer
from lax_connector.room_resume import configured_resume,resume_configured
from lax_connector.project_adoption import cold

async def main():
    os.umask(0o077)
    root=Path(os.environ['ROLE_RECONNECT_EVIDENCE']);root.mkdir(mode=0o700)
    profile=root/'profile';profile.mkdir(mode=0o700)
    (profile/'config.toml').write_text('model_provider="fixture"\nmodel="gpt-6.1-sol"\n[model_providers.fixture]\nname="Unused isolated provider"\nbase_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nrequires_openai_auth=false\n')
    binary=os.environ['ROLE_RECONNECT_BINARY'];socket=root/'native.sock';authority=str(uuid4());host=str(uuid4())
    manifest=dict(schema='lax-native-host/v1',runtimeMode='room-conversation',authorityId=authority,hostId=host,binary=binary,codexHome=str(profile),state=str(root/'native'),socket=str(socket))
    (root/'host.json').write_text(json.dumps(manifest))
    env=dict(os.environ,CODEX_HOME=str(profile),LAX_NATIVE_ENTERPRISE='1',LAX_NATIVE_RUNTIME_MODE='room-conversation');env.pop('LAX_CANONICAL_NATIVE_CHANNEL',None)
    with (root/'native.log').open('xb') as log:
        process=await asyncio.create_subprocess_exec(binary,'--listen','unix://'+str(socket),'-c','check_for_update_on_startup=false',env=env,stdout=log,stderr=log,start_new_session=True)
    clients=[];turns=[]
    async def event(method,params):
        if method=='turn/started':turns.append(params)
    async def forbidden(*args):raise AssertionError('No model/tool callback authorized')
    def client(label,thread=None):
        state=root/label;state.mkdir(mode=0o700)
        value=dict(authorityId=authority,hostId=host,binary=binary,codexHome=str(profile),state=str(state),nativeThreadId=thread,nativeServer={'manifest':str(root/'host.json')})
        rpc=SharedAppServer(value,event,forbidden);clients.append(rpc);return rpc
    def declaration(name):return dict(name=name,description='Owned role binding probe',inputSchema={'type':'object','properties':{},'additionalProperties':False})
    old=[declaration('old_room_probe')];role=[declaration('lead_probe')];instructions={'baseInstructions':'Isolated reviewed lead role.'}
    try:
        for _ in range(100):
            if process.returncode is not None:raise RuntimeError('Owned native fixture exited')
            if socket.exists():break
            await asyncio.sleep(.05)
        rpc=client('original');await rpc.start()
        created=await rpc.call('thread/start',dict(cwd=str(root),model='gpt-6.1-sol',modelProvider='fixture',sandbox='read-only',approvalPolicy='never',baseInstructions='Original fixture role.',dynamicTools=old,config={'thread_unload_delay_secs':600,'features.code_mode':False}))
        thread=created['thread']['id']
        await rpc.call('thread/name/set',{'threadId':thread,'name':'QA role bindings zero-model'})
        await rpc.call('thread/settings/update',{'threadId':thread,'model':created['model'],'effort':'low','approvalPolicy':created['approvalPolicy'],'sandboxPolicy':created['sandbox']})
        (root/'original.json').write_text(json.dumps({'threadId':thread,'originalTools':old,'reviewedTools':role}))
        await cold(rpc,thread,reviewed_instructions=instructions)
        await rpc.call('thread/resume',{'threadId':thread,'excludeTurns':True,**instructions,'dynamicTools':role,'config':{'thread_unload_delay_secs':600}})
        await rpc.close()
        rpc=client('reconnect',thread);await rpc.start()
        params=await configured_resume(rpc,{'threadId':thread,'excludeTurns':True,'config':{'features.default_mode_request_user_input':True}},role)
        await rpc.call('thread/resume',params)
        # Native atomically rejects this assertion if it actually lost the role.
        await rpc.call('thread/resume',{'threadId':thread,'excludeTurns':True,'dynamicTools':role})
        await cold(rpc,thread,reviewed_instructions=instructions)
        params=await configured_resume(rpc,{'threadId':thread,'excludeTurns':True,**instructions,'config':{'thread_unload_delay_secs':600}},role)
        await rpc.call('thread/resume',params)
        await rpc.call('thread/resume',{'threadId':thread,'excludeTurns':True,'dynamicTools':role})
        # An already stale, idle cache is repaired at the existing release boundary.
        await cold(rpc,thread,reviewed_instructions=instructions)
        await rpc.call('thread/resume',{'threadId':thread,'excludeTurns':True,'dynamicTools':old,'config':{'thread_unload_delay_secs':600}})
        restored,binding=await resume_configured(rpc,{'threadId':thread,'excludeTurns':True,'config':{'features.default_mode_request_user_input':True}},role,reviewed_instructions=instructions)
        assert binding['idleCacheRebound'] and restored['thread']['id']==thread
        assert restored['model']==created['model'] and restored['sandbox']==created['sandbox'] and restored['approvalPolicy']==created['approvalPolicy']
        await rpc.call('thread/resume',{'threadId':thread,'excludeTurns':True,'dynamicTools':role})
        assert not turns,turns
        assert process.returncode is None
        result=dict(state='passed',sameThread=thread,loadedReconnectBindingsValidated=True,coldResumeBindingsValidated=True,staleIdleBindingRepaired=True,nativeTurns=0,accountCopied=False,productionChanged=False)
        (root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        for rpc in clients:await rpc.close()
        if process.returncode is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:await asyncio.wait_for(process.wait(),10)
            except asyncio.TimeoutError:os.killpg(process.pid,signal.SIGKILL);await process.wait()
asyncio.run(main())
