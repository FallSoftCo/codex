"""One event-driven lead/worker controller inside the shared host connector.

No additional Codex process, model timer, broadcast fanout or task scheduler in
Hollywood. Native commitment and communication acceptance keep original IDs.
"""
import asyncio
import hashlib
import json
import logging
import random
from uuid import UUID, uuid5
from .lead_work import LeadWork
from .errors import HttpFailure


class ProjectRuntime:
    def __init__(self, owner, policy):
        if not isinstance(policy,dict) or set(policy)!={'version','roomId','leadAgentId','revision'} or policy['version']!=1:
            raise ValueError('Explicit reviewed project communication binding required')
        self.owner=owner;self.policy=policy;self.room=str(UUID(policy['roomId']))
        self.lead=str(UUID(policy['leadAgentId']));self.agent=owner.config['agentId']
        self.ledger=LeadWork(owner.state/'project-work.sqlite',authority=owner.config['authorityId'],room=self.room,agent=self.agent,lead=self.lead)
        with self.ledger.db:self.ledger.db.execute('CREATE TABLE IF NOT EXISTS native_end_notice(turn TEXT PRIMARY KEY,status TEXT NOT NULL)')
        self.wake=asyncio.Event();self.task=None;self.lock=asyncio.Lock()

    async def verify(self):
        value=await self.owner.http('GET','rooms/'+self.room)
        policy=value.get('room',{}).get('leadPolicy',{})
        if (value.get('authorityId')!=self.owner.config['authorityId'] or policy.get('version')!=1
                or policy.get('leadAgentId')!=self.lead or policy.get('revision')!=self.policy['revision']):
            raise ValueError('Canonical lead policy differs from reviewed native role binding')

    async def require_worker(self,agent):
        """Check declared loaded protocol, not inferred work/host availability.

        Uses the existing room-native observation lane. No worker is contacted
        or woken, and no assignment intent is created on a failed preflight.
        """
        agent=str(UUID(agent))
        if agent==self.agent:raise ValueError('Execute local work directly')
        value=await self.owner.http('GET','rooms/'+self.room)
        canonical=value.get('room',{}).get('leadPolicy',{})
        if (value.get('authorityId')!=self.owner.config['authorityId']
                or value.get('room',{}).get('id')!=self.room
                or canonical.get('leadAgentId')!=self.lead
                or canonical.get('revision')!=self.policy['revision']):
            raise ValueError('Canonical project binding is unavailable or changed')
        observations=value.get('nativeState',{}).get('agents',[])
        loaded=[row for row in observations if row.get('agentId')==agent
                and row.get('status',{}).get('projectCommunication')==self.policy]
        if len(loaded)!=1:
            raise ValueError('Selected worker has no current matching project-role observation; no task was sent. Select an attached worker, continue independent work, or report the actual setup dependency. An unaccepted assignment is not a pending worker result.')

    async def candidate(self,event):
        data=event.get('data',{})
        if (data.get('roomMode')!='lead' or data.get('leadAgentId')!=self.lead
                or data.get('leadRevision')!=self.policy['revision']):
            raise ValueError('Received input is outside this reviewed lead-policy epoch')
        if data.get('coordination',{}).get('type')=='answer' and not self.ledger.db.execute("SELECT 1 FROM team_question WHERE event=? AND direction='out'",(event.get('source'),)).fetchone():
            # An answer may arrive before the outgoing question's HTTP ACK.
            # Reconcile retained original question intents, never guess/drop it.
            pending=self.ledger.db.execute('SELECT key FROM team_question_intent WHERE event IS NULL AND task=? AND counterpart=?',
                (data['coordination']['taskId'],event['author'])).fetchall()
            for row in pending:await self.send(row['key'])
        admit,reason=self.ledger.candidate(event)
        return {'admit':admit,'reason':reason}

    def admitted(self,event,turn):
        self.ledger.admitted(event,turn);self.wake.set()

    def ended(self,turn,status):
        with self.ledger.db:self.ledger.db.execute("INSERT INTO native_end_notice VALUES(?,?) ON CONFLICT DO NOTHING",(turn,status))
        self.wake.set()

    async def settle_ends(self):
        rows=self.ledger.db.execute("SELECT n.* FROM native_end_notice n WHERE NOT EXISTS(SELECT 1 FROM native_end e WHERE e.turn=n.turn)").fetchall()
        for row in rows:
            # Both ACK binding and all retained native output must settle before
            # continuation. A failed/unknown publication is not a completed end.
            known=self.ledger.db.execute("SELECT 1 FROM input WHERE turn=? AND admit=1",(row["turn"],)).fetchone()
            if not known:continue
            pending=self.owner.conversation_io.db.execute("SELECT 1 FROM output WHERE turn=? AND state IN ('staged','queued','blocked')",(row["turn"],)).fetchone()
            if pending:continue
            if not self.ledger.is_lead:
                had_final=self.owner.conversation_io.db.execute("SELECT 1 FROM output WHERE turn=?",(row["turn"],)).fetchone()
                if not had_final:await self.worker_missing_result(row["turn"],"empty-turn:"+row["turn"])
            self.ledger.ended(row["turn"],row["status"])

    def causal_source(self,event,turn):
        """Actions retain original work scope; a peer reply does not retarget them.

        Several distinct obligations in one native turn have no guessed source.
        The native input journal still retains their exact individual authorship.
        """
        roots={}
        for row in self.ledger.db.execute('SELECT canonical,work FROM input WHERE turn=? AND admit=1',(turn,)).fetchall():
            item=json.loads(row['canonical'])
            if row['work']:source=json.loads(self.ledger.work(row['work'])['human'])
            else:
                task=item.get('data',{}).get('coordination',{}).get('taskId')
                step=self.ledger.db.execute('SELECT source FROM assignment WHERE id=?',(task,)).fetchone() if task else None
                source=json.loads(step['source']) if step and step['source'] else item
            roots[source['id']]=source
        return next(iter(roots.values())) if len(roots)==1 else None

    def start(self):
        self.ledger.reconcile_waiting()
        self.task=asyncio.create_task(self.run());self.wake.set()

    async def send(self,key):
        async with self.lock:
            row=self.ledger.db.execute('SELECT * FROM outbox WHERE id=?',(key,)).fetchone()
            if not row:raise ValueError('Missing durable communication intent')
            if row['state']=='accepted':return json.loads(row['receipt'])
            if row['state']=='blocked':raise ValueError('Original team communication rejected: '+row['reason'])
            args=json.loads(row['payload'])
            if '_attention' in args:
                request=args['_attention'];identity=request['id'];body=request['body']
                if row['attempted']:
                    receipt=await self.owner.http('GET','attention/'+identity+'/commands/'+body['operationId']+'?roomId='+self.room)
                else:
                    with self.ledger.db:self.ledger.db.execute('UPDATE outbox SET attempted=1 WHERE id=?',(key,))
                    try:receipt=await self.owner.http('POST','attention/'+identity+'/response',body)
                    except Exception:
                        receipt=await self.owner.http('GET','attention/'+identity+'/commands/'+body['operationId']+'?roomId='+self.room)
                if receipt.get('scope')!=body['scope'] or receipt.get('attention',{}).get('response')!=body['response']:
                    raise ValueError('Original callback acceptance is unavailable or mismatched')
                with self.ledger.db:
                    self.ledger.db.execute("UPDATE outbox SET state='accepted',receipt=?,reason=NULL WHERE id=?",(json.dumps(receipt,sort_keys=True),key))
                    step=self.ledger.db.execute('SELECT * FROM assignment WHERE event=?',(body['scope']['sourceEventId'],)).fetchone()
                    if step and step['state']=='question':
                        self.ledger.db.execute("UPDATE assignment SET state='progress' WHERE id=?",(step['id'],))
                        self.ledger.db.execute("UPDATE work SET state='waiting',progress_revision=progress_revision+1,no_progress=0,reason='Worker received its addressed technical answer' WHERE id=? AND state NOT IN ('complete','cancelled','paused')",(step['work'],))
                return receipt
            coord=args.get('coordination',{})
            if coord.get('type')=='task':
                step=self.ledger.db.execute('SELECT * FROM assignment WHERE id=?',(coord['taskId'],)).fetchone()
                work=self.ledger.work(step['work'])
                publication_key=hashlib.sha256(('project:'+key).encode()).hexdigest()
                if work['state'] in ('cancelled','paused') and not (self.owner.tools.state/(publication_key+'.json')).exists():
                    with self.ledger.db:
                        self.ledger.db.execute("UPDATE outbox SET state='cancelled',reason='Stopped before any publication dispatch' WHERE id=?",(key,))
                        self.ledger.db.execute("UPDATE assignment SET state='cancelled' WHERE id=?",(step['id'],))
                    return {'accepted':False,'mayApply':False,'cancelledBeforeDispatch':True}
            # Existing publication ledger distinguishes first dispatch from
            # original-command GET reconciliation after any uncertain result.
            async with self.owner.tools.publish_lock:
                publication_key=hashlib.sha256(('project:'+key).encode()).hexdigest()
                try:receipt=await self.owner.tools.publish(self.room,args,publication_key)
                except HttpFailure as error:
                    publication=self.owner.tools.state/(publication_key+'.json')
                    # A denied original-command GET is NOT proof of non-admission.
                    proof=json.loads(publication.read_text()) if publication.exists() else {}
                    if proof.get('state')=='rejected':self.ledger.rejected(key,str(error))
                    raise
            self.ledger.accepted(key,receipt)
            return receipt

    async def run(self):
        attempts=0
        while True:
            await self.wake.wait();self.wake.clear();retry=False
            await self.settle_ends()
            rows=self.ledger.db.execute("SELECT id FROM outbox WHERE state='ready' ORDER BY rowid").fetchall()
            for row in rows:
                try:await self.send(row['id'])
                except asyncio.CancelledError:raise
                except HttpFailure as error:
                    current=self.ledger.db.execute('SELECT state FROM outbox WHERE id=?',(row['id'],)).fetchone()
                    # send() only blocks with original publication rejection proof.
                    # Ambiguous command reads retain same-ID reconciliation/backoff.
                    if current and current['state']=='blocked':continue
                    payload=json.loads(self.ledger.db.execute('SELECT payload FROM outbox WHERE id=?',(row['id'],)).fetchone()[0])
                    if '_attention' in payload and error.status in (400,403,409):
                        with self.ledger.db:self.ledger.db.execute("UPDATE outbox SET state='blocked',reason=? WHERE id=?",(str(error),row['id']))
                    else:retry=True
                except Exception:
                    logging.getLogger(__name__).exception('Project original communication deferred: %s',row['id']);retry=True
            if retry:
                attempts+=1
                await asyncio.sleep(min(300,2**min(attempts,8))*random.uniform(.8,1.2));self.wake.set()
            else:attempts=0

    async def call(self,name,args,call_id,turn):
        from .project_tools import NAMES
        if name not in NAMES:raise ValueError('Unknown project tool')
        if name=='lead_work':
            if not self.ledger.is_lead:raise PermissionError('Lead work belongs to the canonical lead')
            if 'checkpoint' in args:
                if 'state' in args:raise ValueError('Record a milestone and change disposition in separate calls')
                value=args['checkpoint']
                if not isinstance(value,dict) or set(value)!={'key','summary','evidence'}:raise ValueError('Explicit checkpoint key, summary and evidence required')
                return self.ledger.checkpoint(args['workId'],value['key'],value['summary'],value['evidence'],turn)
            if 'state'in args:
                self.ledger.disposition(args['workId'],args['state'],args.get('reason'));self.wake.set()
            return self.ledger.snapshot(work_id=args.get('workId'),after=args.get('after',0))
        if name=='lead_task':
            row=self.ledger.db.execute('SELECT * FROM assignment WHERE id=?',(str(UUID(args['taskId'])),)).fetchone()
            if not row:raise ValueError('Unknown original assignment')
            return {k:(json.loads(row[k]) if row[k] else None) if k=='result' else row[k] for k in ('id','work','agent','revision','state','brief','event','result')}
        if name=='lead_assign':
            # Original dispatched/accepted assignments reconcile independently
            # of later liveness; never gate their saved receipt on a new GET.
            identity=str(uuid5(UUID(self.agent),'assignment:'+args['workId']+':'+args['taskKey']))
            key='assign:'+identity
            prior=self.ledger.db.execute('SELECT state FROM outbox WHERE id=?',(key,)).fetchone()
            publication=self.owner.tools.state/(hashlib.sha256(('project:'+key).encode()).hexdigest()+'.json')
            if not prior or prior['state']!='accepted' and not publication.exists():
                await self.require_worker(args['agentId'])
            task,key=self.ledger.delegate(args['workId'],args['agentId'],args['brief'],args['taskKey'],args.get('evidence',[]))
            receipt=await self.send(key)
            state=self.ledger.db.execute('SELECT state FROM assignment WHERE id=?',(task,)).fetchone()[0]
            if receipt.get('cancelledBeforeDispatch'):return {'taskId':task,'state':'cancelled','executionConfirmed':False,'cancelledBeforeDispatch':True}
            return {'taskId':task,'state':state,'eventId':receipt['event']['id'],'executionConfirmed':False}
        if name=='team_report':
            key='report:'+args['taskId']+':'+hashlib.sha256(json.dumps(args,sort_keys=True).encode()).hexdigest()
            key=self.ledger.report(args['taskId'],args['outcome'],args['summary'],key,args.get('evidence',[]))
            receipt=await self.send(key)
            return {'state':'reported','eventId':receipt['event']['id']}
        if name=='team_question':
            task=str(UUID(args['taskId']));recipient=str(UUID(args['recipientId']));summary=args['question']
            if recipient==self.agent:raise ValueError('Do not send yourself a peer question')
            if not isinstance(summary,str) or not summary.strip() or len(summary.encode())>1024:raise ValueError('Use a concise peer question, at most1024UTF8 bytes')
            step=self.ledger.db.execute('SELECT * FROM assignment WHERE id=?',(task,)).fetchone()
            incoming=self.ledger.db.execute("SELECT * FROM team_question WHERE task=? AND direction='in' AND state='pending'",(task,)).fetchone()
            work=args.get('workId') or (step['work'] if step and self.ledger.is_lead else None)
            if self.ledger.is_lead:
                if not work:raise ValueError('Lead question must retain its original workId')
                self.ledger.work(work)
            elif not step and not incoming:raise ValueError('Question must belong to assigned work or an addressed incoming question')
            key='question:'+task+':'+recipient+':'+hashlib.sha256(str(args['questionKey']).encode()).hexdigest()
            payload=dict(body=summary,audience='direct',recipientId=recipient,sourceEventId=None,responsePhase='message',coordination=dict(type='question',taskId=task,revision=step['revision'] if step else 1))
            with self.ledger.db:
                self.ledger.queue(key,payload)
                self.ledger.db.execute('INSERT INTO team_question_intent(key,task,work,room,counterpart) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING',(key,task,work,self.room,recipient))
                if step and not self.ledger.is_lead:self.ledger.db.execute("UPDATE assignment SET state='waiting' WHERE id=? AND state IN ('ready','progress')",(task,))
            receipt=await self.send(key)
            return {'questionEventId':receipt['event']['id'],'state':'question_sent','answerReceived':False}
        if name=='team_answer':
            from .team_dialogue import answer_payload
            payload=answer_payload(self.ledger.db,args['questionEventId'],args['summary'])
            key='answer:'+args['questionEventId']
            with self.ledger.db:self.ledger.queue(key,payload)
            receipt=await self.send(key)
            return {'state':'answer_delivered','eventId':receipt['event']['id']}
        if not self.ledger.is_lead:raise PermissionError('Human replies belong to the canonical lead')
        if name=='lead_attention':
            identity=str(UUID(args['attentionId']))
            if 'response' in args:
                prior_key='lead-decision:'+identity+':'+hashlib.sha256(json.dumps(args['response'],sort_keys=True).encode()).hexdigest()
                if self.ledger.db.execute('SELECT 1 FROM outbox WHERE id=?',(prior_key,)).fetchone():return await self.send(prior_key)
            current=await self.owner.http('GET','attention/'+identity+'?roomId='+self.room)
            if 'response' not in args:return current
            if not current.get('canRespond'):raise PermissionError('This callback requires its actual human decision owner')
            key='lead-decision:'+identity+':'+hashlib.sha256(json.dumps(args['response'],sort_keys=True).encode()).hexdigest()
            operation='lead-decision:'+hashlib.sha256(key.encode()).hexdigest()
            with self.ledger.db:self.ledger.queue(key,{'_attention':{'id':identity,'body':{'operationId':operation,'scope':current['scope'],'response':args['response']}}})
            return await self.send(key)
        work=self.ledger.work(args['workId']);human=json.loads(work['human']);disposition=args['disposition']
        if disposition not in ('progress','needs_input','complete'):raise ValueError('Unknown human reply disposition')
        payload=dict(body=args['body'],sourceEventId=human['id'],audience=human['audience'],responsePhase='answer' if disposition=='complete' else 'blocked' if disposition=='needs_input' else 'update')
        if human['audience']=='direct':payload['recipientId']=human['author']
        key='human:'+work['id']+':'+hashlib.sha256(json.dumps({'body':args['body'],'disposition':disposition},sort_keys=True).encode()).hexdigest()
        with self.ledger.db:self.ledger.queue(key,payload)
        receipt=await self.send(key)
        if disposition!='progress':self.ledger.disposition(work['id'],'complete' if disposition=='complete' else 'waiting','Human response '+disposition)
        # Canonical receipt registration suppresses any normal native copy.
        return {'state':'delivered','eventId':receipt['event']['id'],'workState':self.ledger.work(work['id'])['state']}

    async def native_final(self,row,source):
        """Full worker finals stay local. Only structured results reach the lead."""
        await self.peer_final(row)
        if self.ledger.is_lead:
            # Lead responses are deliberately source-bound through lead_reply.
            # A normal final can contain private reasoning about several tasks.
            self.owner.conversation_io.finish(row['item'],'suppressed','Lead final remains private; human response uses lead_reply')
        else:
            await self.worker_missing_result(row['turn'],row['item'])
            self.owner.conversation_io.finish(row['item'],'suppressed','Worker native final retained privately; directed structured result only')
        await self.settle_ends();self.wake.set()
        return True

    async def peer_final(self,row):
        inputs=self.ledger.db.execute('SELECT canonical FROM input WHERE turn=? AND admit=1',(row['turn'],)).fetchall()
        canonical=[json.loads(v['canonical'])for v in inputs]
        only_questions=bool(canonical) and all(e.get('data',{}).get('authorKind')=='agent' and e['data'].get('coordination',{}).get('type') in ('question','answer') for e in canonical)
        tasks={e.get('data',{}).get('coordination',{}).get('taskId') for e in canonical}
        questions=[]
        for task in tasks:
            if not task:continue
            outgoing=self.ledger.db.execute("SELECT 1 FROM team_question_intent i LEFT JOIN team_question q ON q.event=i.event WHERE i.task=? AND (i.event IS NULL OR q.state='pending')",(task,)).fetchone()
            if outgoing:continue  # Actual directed dependency, not completion.
            questions.extend(self.ledger.db.execute("SELECT q.* FROM team_question q JOIN input i ON i.event=q.event WHERE q.task=? AND q.direction='in' AND q.state='pending' AND i.turn IS NOT NULL AND i.admit=1",(task,)).fetchall())
        for question in questions:
            concise=only_questions and len(questions)==1 and row['body'].strip() and len(row['body'].encode())<=1024
            text=row['body'] if concise else 'Native peer turn ended without an attributable concise answer. Its output is retained; report this exact blocker rather than repeatedly asking the unchanged question.'
            from .team_dialogue import answer_payload
            payload=answer_payload(self.ledger.db,question['event'],text)
            if not concise:payload['coordination']['outcome']='failed'
            key='answer:'+question['event']
            with self.ledger.db:self.ledger.queue(key,payload)
            await self.send(key)

    async def worker_missing_result(self,turn,item):
        events=self.ledger.db.execute('SELECT canonical FROM input WHERE turn=? AND admit=1',(turn,)).fetchall()
        for saved in events:
            event=json.loads(saved['canonical']);coord=event.get('data',{}).get('coordination',{})
            if coord.get('type') not in ('task','answer','cancel'):continue
            step=self.ledger.db.execute('SELECT * FROM assignment WHERE id=?',(coord['taskId'],)).fetchone()
            if step and step['state'] in ('ready','progress','cancel_requested'):
                key='missing-result:'+item+':'+step['id']
                self.ledger.report(step['id'],'failed','Native turn ended without a structured task result. Full output is retained in native history; inspect the worker before reassigning.',key)
                await self.send(key)

    async def close(self):
        if self.task:self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        self.ledger.close()
