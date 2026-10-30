"""Two native conversations receive one real canonical PG/HTTP human message.

Bounded account-backed inference only. No business tools, placements, executor
claims or production runtime changes. This proves transport, not full room tools.
"""
import asyncio,json,os,secrets
from uuid import uuid4
from pathlib import Path
from lax_connector.rpc import AppServer
from lax_connector.room_input import submit_human,retain_peer
from hollywood_backbone.store import Store

async def main():
    os.umask(0o077)
    root=Path(os.environ['ROOM_NATIVE_EVIDENCE']);root.mkdir(mode=0o700)
    # Own the complete room fixture; never reuse a privacy test's revoked member.
    fixture_store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
    uid=lambda:str(uuid4())
    intent={'authority':uid(),'room':uid(),
        'credentials':{k:{'principalId':uid(),'token':secrets.token_urlsafe(40)} for k in ('Owner','Global')},
        'actors':{k:{'id':uid(),'token':secrets.token_urlsafe(40)} for k in ('A','B')}}
    (root/'fixture.intent.private.json').write_text(json.dumps(intent))
    owner=intent['credentials']['Owner']['principalId']
    fixture_store.bootstrap(intent['authority'],'SYNTHETIC native conversational journey',{'globalRoomId':uid(),'credentials':intent['credentials']})
    for name,a in intent['actors'].items():
        fixture_store.principal(owner,a['id'],name,'agent',a['token'])
    fixture_store.create_room(owner,intent['room'],'Native input QA','Synthetic input and peer retention',intent['actors']['A']['id'])
    fixture_store.membership(owner,intent['room'],intent['actors']['B']['id'],{'can_read':True,'can_post':True,'can_request':True},0)
    receipt=fixture_store.post(owner,intent['room'],'initial-native-input',{'kind':'message','audience':'room','body':'Synthetic room input check: greet the other participant briefly. Do not call tools.'})
    event=receipt['event']
    for a in intent['actors'].values():
        feed=fixture_store.inbox(a['id'],0,100,False,'conversation')
        assert [e['id'] for e in feed['events']]==[event['id']]
    fixture_store.close()
    config=json.load(open(os.environ['ROOM_NATIVE_ORIGINAL_CONFIG']))
    home=root/'codex-home';home.mkdir();(home/'auth.json').symlink_to(Path(config['codexHome'])/'auth.json')
    notifications=[];completed={};signal=asyncio.Event()
    async def on_event(method,params):
        notifications.append({'method':method,'params':params})
        if method=='turn/completed':completed[params['turn']['id']]=params['turn'];signal.set()
    async def on_request(method,params):raise RuntimeError('No business/tool request authorized in this fixture: '+method)
    rpc=AppServer(config['binary'],home,root/'native',on_event,on_request,enterprise=True)
    try:
        await rpc.start()
        account=await rpc.call('account/read',{'refreshToken':False});assert account.get('account'),'Account unavailable'
        threads={}
        for name in ('A','B'):
            result=await rpc.call('thread/start',{'cwd':str(root),'model':config['model'],'sandbox':'read-only','approvalPolicy':'never','baseInstructions':'You are one participant in a synthetic room input qualification. Respond briefly to the human. Do not call tools or perform work.','config':{'model_reasoning_effort':config['effort']}})
            threads[name]=result['thread']['id']
        (root/'threads.private.json').write_text(json.dumps(threads))
        submissions=[]
        for name in ('A','B'):
            payload={'agent':name,'eventId':event['id'],'nativeThread':threads[name],'submittedOnce':True}
            (root/(name+'-input.intent.json')).write_text(json.dumps(payload))
            response=await submit_human(rpc,event,authority_id=intent['authority'],agent_id=intent['actors'][name]['id'],thread_id=threads[name])
            (root/(name+'-input.accepted.json')).write_text(json.dumps(response));submissions.append(response['turn']['id'])
        async def wait_all():
            while not all(t in completed for t in submissions):
                signal.clear()
                if all(t in completed for t in submissions):break
                await signal.wait()
        await asyncio.wait_for(wait_all(),150)
        assert all(completed[t]['status']=='completed' for t in submissions),completed
        # Two fresh canonical human events exercise start-or-steer on the same
        # persistent thread. No sleep/restart/job claim is used to manufacture busy.
        store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
        try:
            owner=intent['credentials']['Owner']['principalId']
            public1=store.post(owner,intent['room'],'native-busy-'+root.name,{'kind':'message','audience':'room','body':'Synthetic input test only: think carefully and give a concise five-item checklist for a shared conversation. Do not call tools or perform work.'})['event']
            public2=store.post(owner,intent['room'],'native-steer-'+root.name,{'kind':'message','audience':'room','body':'Relevant follow-up to my checklist request: give only two items instead, and end with the exact word ROOMCHECK. Do not call tools.'})['event']
        finally:store.close()
        (root/'busy-input.intent.json').write_text(json.dumps({'first':public1,'followup':public2,'threadId':threads['A']}))
        active=await submit_human(rpc,public1,authority_id=intent['authority'],agent_id=intent['actors']['A']['id'],thread_id=threads['A'])
        active_id=active['turn']['id'];assert active_id not in completed,'Agent became idle before the busy-input check; no resubmission'
        steered=await submit_human(rpc,public2,authority_id=intent['authority'],agent_id=intent['actors']['A']['id'],thread_id=threads['A'])
        assert steered['turn']['id']==active_id,'Busy input created a competing native turn'
        submissions.append(active_id)
        await asyncio.wait_for(wait_all(),150)
        (root/'busy-input.accepted.json').write_text(json.dumps({'first':active,'followup':steered,'firstEventId':public1['id'],'followupEventId':public2['id']}))
        store=Store(json.loads(Path(os.environ['ROOM_NATIVE_DATABASE']).read_text()))
        try:
            peer=store.post(intent['actors']['A']['id'],intent['room'],'native-peer-'+root.name,{'kind':'message','audience':'room','body':'The shared milestone code is ORBITAL7.'})['event']
            ask=store.post(intent['credentials']['Owner']['principalId'],intent['room'],'native-peer-recall-'+root.name,{'kind':'message','audience':'room','body':'What milestone code did agent A just contribute? Answer only with that code; do not call tools.'})['event']
        finally:store.close()
        turns_before=sum(n['method']=='turn/started' for n in notifications)
        await retain_peer(rpc,peer,authority_id=intent['authority'],agent_id=intent['actors']['B']['id'],thread_id=threads['B'])
        assert sum(n['method']=='turn/started' for n in notifications)==turns_before,'Passive peer publication woke a model'
        recalled=await submit_human(rpc,ask,authority_id=intent['authority'],agent_id=intent['actors']['B']['id'],thread_id=threads['B'])
        submissions.append(recalled['turn']['id']);await asyncio.wait_for(wait_all(),150)
        histories={}
        for name in ('A','B'):
            histories[name]=await rpc.call('thread/read',{'threadId':threads[name],'includeTurns':True})
        assistant=lambda h:[item.get('text','') for turn in h['thread']['turns'] for item in turn.get('items',[]) if item.get('type')=='agentMessage']
        assert any('ROOMCHECK' in text for text in assistant(histories['A'])),'Follow-up missing from actual assistant output'
        assert any('ORBITAL7' in text for text in assistant(histories['B'])),'Retained peer contribution missing from actual assistant output'
        (root/'histories.private.json').write_text(json.dumps(histories,indent=2))
        result={'passed':True,'nativeProcessPid':rpc.process.pid,'independentThreads':len(set(threads.values())),'sameCanonicalEvent':event['id'],'submittedNativeTurns':len(submissions),'completedNativeTurns':len(completed),'model':config['model'],'effort':config['effort'],'hollywoodExecutorClaims':0,'productionChanged':False,'roomToolsQualified':False,'busyInputSameTurn':steered['turn']['id']==active_id,'passivePeerStartedTurns':0,'peerRecalledByModel':True}
        (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        await rpc.close();(root/'notifications.private.json').write_text(json.dumps(notifications))
asyncio.run(main())
