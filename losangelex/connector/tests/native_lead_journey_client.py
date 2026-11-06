"""Bounded actual native lead/selected-worker/observer qualification client.

Uses the existing shared host profile and three new, named QA contexts. Does
not enroll services, copy account authentication, start another app-server or
access business rooms. Root fixture owns isolated HTTP/SQL and original input.
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from lax_connector.room_bootstrap import initialize
from lax_connector.conversational_agent import ConversationalAgent
from lax_connector.journal import saved
from lax_connector.rpc_shared import native_client


async def main(file):
    file=Path(file);plan=json.loads(file.read_text());root=file.parent
    agents=[];tasks=[];events=[];archived=[];failure=None
    try:
        for config in plan['clients']:
            original=await initialize(config)
            config['nativeThreadId']=original['nativeThreadId']
            saved(Path(config['state'])/'qa-client-config.private.json',config)
            agent=ConversationalAgent(config);original_event=agent.rpc.on_event
            async def observe(method,params,*,target=agent,callback=original_event):
                if params.get('threadId')==target.thread:
                    if method in ('turn/started','turn/completed','error'):
                        events.append({'at':time.time(),'agentId':target.config['agentId'],'method':method,'params':params})
                        saved(root/'native-events.private.json',events)
                await callback(method,params)
            agent.rpc.on_event=observe
            agents.append(agent);tasks.append(asyncio.create_task(agent.serve()))
        deadline=time.monotonic()+40
        while True:
            for task in tasks:
                if task.done():task.result();raise RuntimeError('QA client unexpectedly stopped')
            if all(a.listeners and all(listener.ready.is_set()for listener in a.listeners)for a in agents):break
            if time.monotonic()>deadline:raise TimeoutError('QA input subscriptions did not become ready')
            await asyncio.sleep(.1)
        saved(root/'client-status.json',{'state':'ready','nativeThreads':[a.thread for a in agents],'modelTurnsStarted':0})
        deadline=time.monotonic()+360
        while True:
            for task in tasks:
                if task.done():task.result();raise RuntimeError('QA native client stopped')
            lead=agents[0];work=lead.project.ledger.db.execute('SELECT * FROM work').fetchall()
            pending=any(a.conversation_io.pending() or a.native_active_turn for a in agents)
            if work and all(r['state']=='complete'for r in work) and not pending:
                break
            if any(r['state']=='fault'for r in work):raise RuntimeError('Actual lead reached a no-progress/native fault')
            if time.monotonic()>deadline:raise TimeoutError('Actual lead did not complete bounded QA work')
            await asyncio.sleep(.2)
        started=[e for e in events if e['method']=='turn/started']
        counts={a.config['agentId']:sum(e['agentId']==a.config['agentId']for e in started)for a in agents}
        if plan.get('evidenceProof'):
            assert counts[agents[0].config['agentId']]==2
            ledger=agents[0].project.ledger
            assert ledger.db.execute('SELECT count(*) FROM completion_receipt').fetchone()[0]==1
            assert ledger.db.execute('SELECT count(*) FROM evidence_blob').fetchone()[0]>=2
        elif plan.get('localProgress'):
            assert counts[agents[0].config['agentId']]==3 and all(counts[a.config['agentId']]==0 for a in agents[1:])
            checkpoints={r[0] for r in agents[0].project.ledger.db.execute('SELECT key FROM local_checkpoint')}
            assert {'local-phase-1','local-phase-2'}<=checkpoints
        else:
            assert counts[agents[0].config['agentId']]>0 and counts[agents[1].config['agentId']]>0
        if plan.get('peerDialogue'):assert counts[agents[2].config['agentId']]>0
        if len(agents)>1:assert counts[agents[-1].config['agentId']]==0
        snapshots=[a.project.ledger.snapshot()for a in agents]
        saved(root/'native-result.private.json',{'passed':True,'actualNativeInference':True,'existingSharedAppServer':True,'newAppServers':0,'turnCounts':counts,'snapshots':snapshots})
    except BaseException as error:
        failure=error;saved(root/'client-failure.json',{'type':type(error).__name__,'message':str(error),'activeTurns':[{ 'threadId':a.thread,'turnId':a.native_active_turn}for a in agents if a.native_active_turn]})
    finally:
        # Interrupt only still-active owned QA turns, never another host agent.
        for agent in agents:
            if agent.native_active_turn:
                turn=agent.native_active_turn
                intent=root/('interrupt-'+turn+'.json')
                if intent.exists():continue
                saved(intent,{'state':'dispatching','threadId':agent.thread,'turnId':turn})
                try:
                    reply=await agent.rpc.call('turn/interrupt',{'threadId':agent.thread,'turnId':turn})
                    saved(intent,{'state':'acknowledged','threadId':agent.thread,'turnId':turn,'reply':reply})
                except Exception as error:saved(intent,{'state':'unknown','threadId':agent.thread,'turnId':turn,'error':str(error)})
        limit=time.monotonic()+15
        while any(a.native_active_turn for a in agents) and time.monotonic()<limit:await asyncio.sleep(.1)
        active=[a.thread for a in agents if a.native_active_turn]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        for agent in agents:
            if agent.thread in active:continue
            async def discard(*args):pass
            rpc=native_client(agent.config,discard,discard)
            try:
                await rpc.start()
                meta=await rpc.call('thread/read',{'threadId':agent.thread,'includeTurns':False})
                if meta['thread']['status']['type']=='active':continue
                await rpc.call('thread/archive',{'threadId':agent.thread});archived.append(agent.thread)
            finally:await rpc.close()
        saved(root/'client-cleanup.json',{'archivedQaThreads':archived,'unsettledQaThreads':active,'existingAppServerStopped':False})
        if active:failure=failure or RuntimeError('Owned QA native outcome remains unsettled')
    if failure:raise failure


if __name__=='__main__':asyncio.run(main(sys.argv[1]))
