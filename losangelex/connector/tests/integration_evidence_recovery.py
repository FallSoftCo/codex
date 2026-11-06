"""Actual durable ledger/runtime restart journeys; native metadata is controlled.

No production/model calls. Native command provenance requires a separate journey.
"""
import asyncio,hashlib,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from lax_connector.project_runtime import ProjectRuntime
from lax_connector.conversation_io import ConversationIO
from lax_connector.room_receive import RoomReceiveJournal
from lax_connector.room_session_inspect import journal_counts


def rejected(fn):
    try:fn()
    except ValueError:return
    raise AssertionError('Unsafe operation accepted')


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        state=Path(tmp);room,lead,authority,human=[str(uuid4()) for _ in range(4)]
        config={'agentId':lead,'authorityId':authority,'nativeThreadId':'original-thread','state':str(state),'rooms':[]}
        owner=SimpleNamespace(state=state,config=config,thread='original-thread',attention=SimpleNamespace(pending={}),rpc=None)
        owner.conversation_io=ConversationIO(state/'conversation-io.sqlite',authority=authority,agent=lead,thread=owner.thread)
        policy={'version':1,'roomId':room,'leadAgentId':lead,'revision':1}
        runtime=ProjectRuntime(owner,policy);l=runtime.ledger
        def original(turn):
            event={'id':str(uuid4()),'room':room,'author':human,'body':'Verify actual build and release','audience':'room','data':{'authorKind':'human','roomMode':'lead','leadAgentId':lead,'leadRevision':1}}
            assert l.candidate(event)[0];l.admitted(event,turn)
            return l.db.execute('SELECT work FROM input WHERE event=?',(event['id'],)).fetchone()[0]
        work=original('build-turn')
        rejected(lambda:l.disposition(work,'complete','It looks ready'))
        await runtime.call('lead_work',{'workId':work,'acceptance':{'subject':'commit:original','reason':'Original requested behavior and delivery','criteria':[{'id':'build','requirement':'Build succeeds'},{'id':'delivery','requirement':'Delivered artifact matches verified build'}]}},'criteria','build-turn')
        artifact=state/'build.json';artifact.write_text('{"actualTest":"pass"}\n');sha=hashlib.sha256(artifact.read_bytes()).hexdigest()
        proof={'key':'build-proof','criterion':'build','verdict':'pass','summary':'Actual command result and retained receipt','artifacts':[{'path':str(artifact),'sha256':sha}],'native':{'turnId':'build-turn','itemId':'command-1'}}
        try:await runtime.call('lead_work',{'workId':work,'verification':proof},'unattested','build-turn');raise AssertionError('Unattested execution accepted')
        except ValueError:pass
        l.evidence.native_command('build-turn',{'type':'commandExecution','id':'command-1','command':'verify build','cwd':tmp,'status':'completed','exitCode':0,'aggregatedOutput':'pass '+sha})
        first=await runtime.call('lead_work',{'workId':work,'verification':proof},'verify','build-turn')
        progress=l.work(work)['progress_revision'];await runtime.call('lead_work',{'workId':work,'verification':{**proof,'key':'same-material'}},'same','build-turn');assert l.work(work)['progress_revision']==progress
        rejected(lambda:l.disposition(work,'complete','One criterion missing'))
        artifact.unlink();l.close();runtime=ProjectRuntime(owner,policy);l=runtime.ledger
        assert await runtime.call('lead_work',{'workId':work,'verification':proof},'retry','build-turn')==first
        assert l.evidence.snapshot(work)['verifications'] and l.db.execute('SELECT count(*) FROM evidence_blob').fetchone()[0]==1
        artifact.write_text('{"delivery":"pass"}');proof2={**proof,'key':'delivery-proof','criterion':'delivery','artifacts':[{'path':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}]}
        l.evidence.native_command('build-turn',{'type':'commandExecution','id':'command-2','command':'verify delivery','cwd':tmp,'status':'completed','exitCode':0,'aggregatedOutput':proof2['artifacts'][0]['sha256']})
        proof2['native']={'turnId':'build-turn','itemId':'command-2'}
        await runtime.call('lead_work',{'workId':work,'verification':proof2},'deliver','build-turn')
        with l.db:l.evidence.seal(work)
        rejected(lambda:l.evidence.define(work,{'subject':'changed','reason':'different revision','criteria':[{'id':'build','requirement':'Build succeeds'}]},'build-turn'))
        l.disposition(work,'complete','Both criteria verified');sealed=l.evidence.snapshot(work)['completion'];l.close();runtime=ProjectRuntime(owner,policy);l=runtime.ledger;assert l.evidence.snapshot(work)['completion']==sealed
        # Actual SQLite reopen, interrupted stops, provider failures and unknown I/O.
        recovering=original('failed-turn');error={'codexErrorInfo':'serverOverloaded','message':'capacity'};l.ended('failed-turn','failed',error);assert l.work(recovering)['state']=='recovering';due=l.recovery.next_due();l.close();runtime=ProjectRuntime(owner,policy);l=runtime.ledger;assert l.recovery.next_due()==due
        calls=[]
        class RPC:
            async def call(self,method,args):
                calls.append(method)
                if method=='thread/read':return {'thread':{'id':owner.thread,'status':{'type':'systemError'}}}
                if method=='thread/backgroundTerminals/list':return {'data':[],'nextCursor':None}
                if method=='thread/turns/list':return {'data':[{'id':'failed-turn','status':'failed','error':error}]}
                raise AssertionError('Execution attempted')
        config['rooms']=[{'roomId':room}]
        receives=RoomReceiveJournal(state/'rooms'/room/'receive.sqlite')
        observed=str(uuid4());receives.stage(authority=authority,agent=lead,event=observed,thread=owner.thread,seq=1,payload={'method':'turn/start'})
        assert journal_counts(config)['uncertainHandoffs']==1
        receives.observe_only(authority,lead,observed,'Attributable observation, not an assignment')
        assert journal_counts(config)['uncertainHandoffs']==0
        receives.close();receives=RoomReceiveJournal(state/'rooms'/room/'receive.sqlite')
        assert journal_counts(config)['uncertainHandoffs']==0
        owner.rpc=RPC();owner.conversation_io.db.execute("INSERT INTO publication VALUES('failed-turn',NULL,'uncertain','r','attempting')");owner.conversation_io.db.commit()
        await l.recovery.inspect_due(owner,now=due+1);assert l.work(recovering)['state']=='recovering' and l.recovery.next_due()>due
        for _ in range(12):
            at=l.recovery.next_due()+1;await l.recovery.inspect_due(owner,now=at);assert l.work(recovering)['state']=='recovering' and 0<l.recovery.next_due()-at<=3600
        owner.conversation_io.db.execute("UPDATE publication SET state='accepted'");owner.conversation_io.db.commit()
        await l.recovery.inspect_due(owner,now=l.recovery.next_due()+1);assert l.work(recovering)['state']=='ready'
        wake=l.db.execute("SELECT count(*) FROM outbox WHERE id LIKE ?",('ready:'+recovering+':%',)).fetchone()[0];await l.recovery.inspect_due(owner,now=due+10000);assert l.db.execute("SELECT count(*) FROM outbox WHERE id LIKE ?",('ready:'+recovering+':%',)).fetchone()[0]==wake==1
        # A later uncertain handoff must not inherit the observation exemption.
        receives.begin_handoff(authority,lead,observed)
        assert journal_counts(config)['uncertainHandoffs']==1
        receives.close()
        # No model retry for deliberate interruption, usage stop or actual revocation.
        for turn,code,status in [('stop',None,'interrupted'),('usage','usageLimitExceeded','failed'),('permission','unauthorized','failed')]:
            wid=original(turn);l.ended(turn,status,{'codexErrorInfo':code});assert l.work(wid)['state'] in ('paused','fault')
        # Two unproductive ends produce one durable diagnostic opportunity.
        wid=original('stalled-1');l.ended('stalled-1','completed')
        def admit_wake(work,turn):
            r=l.db.execute("SELECT payload FROM outbox WHERE id LIKE ? ORDER BY rowid DESC LIMIT 1",('ready:'+work+':%',)).fetchone();payload=json.loads(r[0]);e={'id':str(uuid4()),'room':room,'author':lead,'recipient':lead,'body':payload['body'],'data':{'coordination':payload['coordination']}}
            assert l.candidate(e)[0];l.admitted(e,turn)
        admit_wake(wid,'stalled-2');l.ended('stalled-2','completed');assert l.work(wid)['state']=='recovering'
        # A metadata-verified diagnostic was released; no second unchanged model cycle.
        with l.db:l.db.execute("UPDATE work_recovery SET state='released' WHERE work=?",(wid,));l.db.execute("UPDATE work SET state='working' WHERE id=?",(wid,));l.db.execute('INSERT INTO turn_work VALUES(?,?,?)',('diagnostic',wid,l.work(wid)['progress_revision']))
        l.ended('diagnostic','completed');assert l.work(wid)['state']=='fault'
        assert all(method.startswith('thread/') and method not in ('thread/resume','thread/start') for method in calls)
        l.close();owner.conversation_io.close()
    print(json.dumps({'passed':True,'durableEvidenceAndCompletion':True,'restartPreservesRecovery':True,'unknownPublicationNotReplayed':True,'stopsPreserved':True,'sameRecoveryWakeOnce':True,'observationNeverWaivesActualHandoff':True,'unchangedDiagnosticBounded':True,'nativeModelCalls':0}))

if __name__=='__main__':asyncio.run(main())
