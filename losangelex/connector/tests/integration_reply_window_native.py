"""Frozen three-context native/PG/HTTP semantic journey, no business actions."""
import asyncio,json,os,time
from pathlib import Path
from aiohttp import ClientSession
from lax_connector.rpc_shared import SharedAppServer
from lax_connector.conversation_io import ConversationIO
from lax_connector.room_runtime import RoomRuntime
from lax_connector.room_output import RoomOutput
from lax_connector.room_tools import RoomTools,TOOLS
from lax_connector.room_reply_window import ReplyWindow
from lax_connector.errors import HttpFailure

ROOT=Path(os.environ['MODEL_REPLY_ROOT'])
async def main():
    os.umask(0o077)
    setup=json.loads((ROOT/'setup.private.json').read_text())
    path=ROOT/'native-result.private.json'
    if path.exists():raise RuntimeError('Reconcile original model run; do not replay it')
    config=json.loads(Path(os.environ['REPLY_NATIVE_CONFIG']).read_text())
    results={'started':time.time(),'criteria':'Frozen in acceptance.json before execution','stages':[],'agents':[]}
    path.write_text(json.dumps(results))
    traces=[];clients=[];ios=[];outputs=[];runtimes=[];listeners=[];active={}
    def save():path.write_text(json.dumps({**results,'trace':traces},ensure_ascii=False,indent=2))
    try:
        async with ClientSession() as session:
            async def create(i,a):
                state=ROOT/str(i);state.mkdir(mode=0o700)
                async def request(method,target,payload=None):
                    async with session.request(method,setup['base']+target,json=payload,headers={'Authorization':'Bearer '+a['token']}) as response:
                        value=await response.json()
                        traces.append({'agent':i,'type':'http','method':method,'path':target,'status':response.status,'result':value});save()
                        if response.status!=200:raise HttpFailure(response.status,str(value))
                        return value
                holder={}
                async def observe(method,p):
                    traces.append({'agent':i,'type':'native','method':method,'params':p})
                    io=holder.get('io');output=holder.get('output')
                    if method=='turn/started':active[i]=p['turn']['id']
                    if io and method=='item/completed' and p['item'].get('type')=='agentMessage' and p['item'].get('phase') in (None,'final_answer'):
                        io.final(p['turnId'],p['item']['id'],p['item'].get('text',''))
                    if io and method=='turn/completed':
                        io.ended(p['turn']['id'],p['turn'].get('status','completed'));active.pop(i,None)
                    if output:output.wake.set()
                    save()
                async def callback(method,p):
                    if method!='item/tool/call' or p.get('tool') not in {'hollywood_publish','hollywood_read_room','hollywood_context'}:
                        raise RuntimeError('QA authorizes only room read/publish, no business actions')
                    return await holder['tools'].call(method,p)
                c={**config,'nativeThreadId':None,'state':str(state)}
                rpc=SharedAppServer(c,observe,callback);clients.append(rpc)
                await rpc.start()
                base=('You are '+a['name']+' in a synthetic room communication qualification. '
                    'No business execution, files, shell commands, external tools, assignments or permissions changes are authorized. '
                    'Answer the human question using this verified host-specific fact: '+a['fact']+' '
                    'Do not infer settings of other hosts. Keep your answer concise. Every room member receives the same input. '
                    'Ordinary final answers are automatically considered for publication; explicit hollywood_publish is also available. '
                    'When application reply-review feedback arrives, judge whether you have useful information beyond the peer reply. '
                    'Publish a useful addition with its original source or abstain without publishing if redundant. Do not send acknowledgements.')
                created=await rpc.call('thread/start',{'cwd':str(state),'model':config['model'],'approvalPolicy':'never',
                    'sandbox':'danger-full-access','dynamicTools':TOOLS,'baseInstructions':base,
                    'config':{'model_reasoning_effort':config['effort']}})
                thread=created['thread']['id'];results['agents'].append({'i':i,'name':a['name'],'thread':thread,'fact':a['fact']});save()
                io=ConversationIO(state/'io.sqlite',authority=setup['authority'],agent=a['id'],thread=thread);ios.append(io);holder['io']=io
                tools=RoomTools(authority_id=setup['authority'],agent_id=a['id'],thread_id=thread,request=request,
                    state=state/'publications',conversation_io=io);holder['tools']=tools
                tools.reply_window=ReplyWindow(io,rpc,idle=lambda:i not in active);io.reply_window=tools.reply_window
                output=RoomOutput(io,tools);holder['output']=output;outputs.append(output)
                async def before(event):io.stage(event)
                async def receipt(event,reply):io.bind(event,reply);output.wake.set()
                async def own(event):
                    if io.observe_own_reply(event):output.wake.set()
                runtime=RoomRuntime(rpc=rpc,session=session,base_url=setup['base'],token=a['token'],authority_id=setup['authority'],
                    agent_id=a['id'],room_id=setup['room'],thread_id=thread,state=state/'receive',initial_cursor=setup['source']['seq']-1,
                    on_room_event=own,before_native_input=before,on_native_receipt=receipt)
                runtimes.append(runtime);output.start();listeners.append(asyncio.create_task(runtime.run()))
                return io,rpc
            await asyncio.gather(*(create(i,a) for i,a in enumerate(setup['agents'])))
            results['stages'].append('three original native inputs admitted through room runtimes');save()
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                # Bounded qualification observation only, NOT product model polling.
                if not active and all(io.db.execute('SELECT count(*) FROM native_end').fetchone()[0]>0 for io in ios):
                    pending=sum(io.db.execute("SELECT count(*) FROM output WHERE state IN ('staged','queued')").fetchone()[0] for io in ios)
                    reviewing=sum(io.db.execute('SELECT count(*) FROM reply_review r LEFT JOIN native_end n ON n.turn=r.turn WHERE n.turn IS NULL').fetchone()[0] for io in ios)
                    if not pending and not reviewing:break
                await asyncio.sleep(.2)
            else:raise TimeoutError('Owned model journey did not settle within frozen deadline')
            a=setup['agents'][0]
            async with session.get(setup['base']+'rooms/'+setup['room']+'/history?view=conversation&limit=100',headers={'Authorization':'Bearer '+a['token']}) as r:
                history=await r.json();assert r.status==200,history
            answers=[e for e in history['events'] if e['kind']=='message' and e['data'].get('authorKind')=='agent']
            results['history']=history
            assert len(answers)==2,[(e['author'],e['body']) for e in answers]
            assert all(e['source']==setup['source']['id'] and e['audience']=='room' for e in answers)
            texts=' '.join(e['body'] for e in answers).lower()
            assert 'gpt-6.1-sol' in texts and 'gpt-6-astra' in texts and 'xhigh' in texts,texts
            histories=[]
            for rpc in clients:
                h=await rpc.call('thread/read',{'threadId':rpc.thread_id,'includeTurns':True});histories.append(h)
                users=[x for t in h['thread']['turns'] for x in t.get('items',[]) if x['type']=='userMessage']
                assert len(users)==1,(rpc.thread_id,users)
            results['nativeHistories']=histories
            results.update(passed=True,completed=time.time());save()
    finally:
        for listener in listeners:listener.cancel()
        await asyncio.gather(*listeners,return_exceptions=True)
        for o in outputs:await o.close()
        for rpc in clients:
            # Archive only this test's known completed contexts, never shared daemon.
            try:
                if rpc.thread_id and not active:await rpc.call('thread/archive',{'threadId':rpc.thread_id})
            finally:await rpc.close()
        for runtime in runtimes:runtime.close()
        for io in ios:io.close()
        save()
    print(json.dumps({'passed':results.get('passed',False),'duration':results.get('completed',time.time())-results['started'],
        'replies':[e['body'] for e in results.get('history',{}).get('events',[]) if e['data'].get('authorKind')=='agent']}))

asyncio.run(main())
