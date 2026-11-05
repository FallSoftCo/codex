"""Durable project work owned by LAX, never by the room transport.

Only accepted human intent creates work. Results change its revision; unchanged
blocks do not sample a model. A native final without a disposition gets at most
one repair opportunity. Transport reconciliation never fabricates task success.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from uuid import UUID, uuid5
from .runtime_files import state_directory


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class LeadWork:
    def __init__(self, path, *, authority, room, agent, lead):
        path=Path(path);state_directory(path.parent,parents=True,exist_ok=True)
        os.close(os.open(path,os.O_CREAT|os.O_RDWR,0o600))
        self.db=sqlite3.connect(path);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.agent=str(UUID(agent));self.lead=str(UUID(lead));self.room=str(UUID(room))
        self.is_lead=self.agent==self.lead
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS binding(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS work(id TEXT PRIMARY KEY,source TEXT UNIQUE NOT NULL,
            human TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL,reason TEXT,
            no_progress INTEGER NOT NULL DEFAULT 0,progress_revision INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS assignment(id TEXT PRIMARY KEY,work TEXT,agent TEXT NOT NULL,
            revision INTEGER NOT NULL,state TEXT NOT NULL,brief TEXT NOT NULL,event TEXT,
            source TEXT,last_material TEXT,result TEXT);
          CREATE INDEX IF NOT EXISTS assignment_work ON assignment(work,state);
          CREATE TABLE IF NOT EXISTS input(event TEXT PRIMARY KEY,digest TEXT NOT NULL,
            canonical TEXT NOT NULL,work TEXT,admit INTEGER NOT NULL,reason TEXT NOT NULL,turn TEXT);
          CREATE INDEX IF NOT EXISTS input_turn ON input(turn,work);
          CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'ready',receipt TEXT,reason TEXT);
          CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(state,id);
          CREATE TABLE IF NOT EXISTS native_end(turn TEXT PRIMARY KEY,status TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS turn_work(turn TEXT NOT NULL,work TEXT NOT NULL,
            progress_revision INTEGER NOT NULL,PRIMARY KEY(turn,work));
        ''')
        from .team_dialogue import SCHEMA as DIALOGUE_SCHEMA
        self.db.executescript(DIALOGUE_SCHEMA)
        if 'attempted' not in {r['name'] for r in self.db.execute('PRAGMA table_info(outbox)')}:
            with self.db:self.db.execute('ALTER TABLE outbox ADD COLUMN attempted INTEGER NOT NULL DEFAULT 0')
        binding=encoded(dict(authority=str(UUID(authority)),room=self.room,agent=self.agent,lead=self.lead))
        with self.db:
            self.db.execute('INSERT INTO binding VALUES(1,?) ON CONFLICT DO NOTHING',(binding,))
            if self.db.execute('SELECT value FROM binding').fetchone()[0]!=binding:
                raise ValueError('Project work ledger belongs to another room/role')

    def close(self):self.db.close()

    def work(self, identity):
        row=self.db.execute('SELECT * FROM work WHERE id=?',(str(UUID(identity)),)).fetchone()
        if not row:raise ValueError('Unknown original human work')
        return dict(row)

    def adopt_original(self, event, state, reason):
        """Import a reviewed obligation; never deliver its human text again.

        The operator verifies the original event against canonical Hollywood.
        Only an explicitly ready entry queues one source-bound work-ready event.
        Stops, completed work and uncertain external effects remain non-running.
        """
        if not self.is_lead or event.get('room')!=self.room or event.get('data',{}).get('authorKind')!='human':
            raise ValueError('Only the lead imports original canonical human work')
        if state not in ('ready','paused','cancelled','complete','fault'):
            raise ValueError('Review original dependencies before marking work ready; unknown work remains faulted')
        if not isinstance(reason,str) or not reason.strip() or len(reason.encode())>2048:
            raise ValueError('A bounded reviewed work disposition is required')
        if self.agent not in event.get('data',{}).get('conversationRecipients',[]):
            raise ValueError('The original request did not address this lead')
        identity=str(uuid5(UUID(self.agent),'human:'+event['id']))
        with self.db:
            old=self.db.execute('SELECT * FROM work WHERE id=?',(identity,)).fetchone()
            if old:
                if old['human']!=encoded(event):raise ValueError('Retained original work changed')
                # A repeated accepted handover cannot reset subsequent work.
                return identity
            self.db.execute('INSERT INTO work(id,source,human,state,revision,reason) VALUES(?,?,?,?,1,?)',
                (identity,event['id'],encoded(event),state,reason))
            self.db.execute('INSERT INTO input(event,digest,canonical,work,admit,reason) VALUES(?,?,?,?,0,?)',
                (event['id'],sha(event),encoded(event),identity,'Reviewed retained input; never a new human admission'))
            if state=='ready':self.ready_event(identity,1)
        return identity

    def ready_event(self,work,revision):
        record=self.work(work)
        coord=dict(type='wake',taskId=work,revision=revision,originEventId=record['source'])
        args=dict(body='Owned work is ready. Inspect lead_work; reconcile retained evidence and continue useful work or record its real dependency/completion.',audience='direct',recipientId=self.agent,sourceEventId=None,responsePhase='message',coordination=coord)
        return self.queue('ready:'+work+':'+str(revision),args)

    def candidate(self, event):
        """Persist one admission decision before native start/steer. Idempotent."""
        if event['room']!=self.room:raise ValueError('Project input room differs')
        fingerprint=sha(event);old=self.db.execute('SELECT * FROM input WHERE event=?',(event['id'],)).fetchone()
        if old:
            if old['digest']!=fingerprint:raise ValueError('Canonical project input changed')
            return bool(old['admit']),old['reason']
        data=event.get('data',{});coord=data.get('coordination',{});typ=coord.get('type')
        work=None;admit=False;reason='Stored team observation, no native context admission'
        with self.db:
            if data.get('authorKind')=='human':
                if not self.is_lead:raise PermissionError('Only the lead accepts human project input')
                work=str(uuid5(UUID(self.agent),'human:'+event['id']))
                self.db.execute("INSERT INTO work(id,source,human,state,revision) VALUES(?,?,?,'ready',1)",
                    (work,event['id'],encoded(event)))
                admit=True;reason='New original human work'
            elif typ=='task':
                if event['author']!=self.lead or event.get('recipient')!=self.agent:
                    raise PermissionError('Task must come from the canonical project lead')
                task=str(UUID(coord['taskId']))
                prior=self.db.execute('SELECT * FROM assignment WHERE id=?',(task,)).fetchone()
                if prior:raise ValueError('Existing assignment cannot be overwritten by another event')
                self.db.execute("INSERT INTO assignment(id,agent,revision,state,brief,event,source) VALUES(?,?,?,'ready',?,?,?)",
                    (task,self.agent,coord['revision'],event['body'],event['id'],encoded(event)))
                admit=True;reason='Addressed lead assignment'
            elif typ=='answer':
                from .team_dialogue import answer_received
                question,changed=answer_received(self.db,event);work=question['work'];admit=changed
                reason='Addressed answer to an outstanding question' if changed else 'Previously answered question, no new native input'
                if changed and work:
                    self.db.execute("UPDATE work SET state='ready',revision=revision+1,progress_revision=progress_revision+1,no_progress=0 WHERE id=? AND state NOT IN ('complete','cancelled','paused')",(work,))
                elif changed:self.db.execute("UPDATE assignment SET state='ready' WHERE id=? AND state IN ('waiting','question')",(question['task'],))
            elif typ=='question' and not data.get('attentionId'):
                from .team_dialogue import incoming
                step=self.db.execute('SELECT * FROM assignment WHERE id=?',(coord['taskId'],)).fetchone()
                work=step['work'] if self.is_lead and step else None
                incoming(self.db,event,work);admit=not work or self.work(work)['state'] not in ('complete','cancelled','paused');reason='Explicit addressed peer question' if admit else 'Stopped work retains peer question without model activation'
                if work:self.db.execute("UPDATE work SET state='ready',revision=revision+1 WHERE id=? AND state NOT IN ('complete','cancelled','paused')",(work,))
            elif typ in ('result','question') and self.is_lead:
                task=str(UUID(coord['taskId']));step=self.db.execute('SELECT * FROM assignment WHERE id=?',(task,)).fetchone()
                if not step or step['agent']!=event['author'] or step['revision']!=coord['revision']:
                    raise ValueError('Peer update does not belong to this original assignment')
                if step['state'] in ('done','cancelled'):reason='Terminal assignment retains late observations without a wake'
                else:
                    work=step['work'];material=sha(dict(type=typ,body=event['body'],outcome=coord.get('outcome'),evidence=coord.get('evidence',[]),attentionId=data.get('attentionId')))
                    if material!=step['last_material']:
                        state='question' if typ=='question' else coord['outcome']
                        self.db.execute('UPDATE assignment SET state=?,last_material=?,result=? WHERE id=?',
                            (state,material,encoded(event),task))
                        # Late results of complete/stopped work remain inspectable;
                        # they cannot revive it or enroll historical tasks.
                        actionable=typ=='question' or coord.get('outcome') in ('done','blocked','failed','cancelled')
                        if actionable:
                            changed=self.db.execute("UPDATE work SET state='ready',revision=revision+1,progress_revision=progress_revision+1,no_progress=0 WHERE id=? AND state NOT IN ('complete','cancelled','paused')",(work,)).rowcount
                            admit=bool(changed);reason='Material selected-worker '+typ if changed else 'Historical result retained'
                        else:
                            self.db.execute("UPDATE work SET progress_revision=progress_revision+1 WHERE id=?",(work,))
                            reason='Progress retained for deliberate inspection; no lead decision or terminal result'
                    else:reason='Unchanged dependency/result retained without a model wake'
            elif typ=='wake' and self.is_lead:
                work=str(UUID(coord['taskId']));record=self.work(work)
                if (event['author']!=self.agent or event.get('recipient')!=self.agent
                        or coord.get('originEventId')!=record['source']):
                    raise PermissionError('Work-ready event must retain its real owner and original intent')
                admit=record['state']=='ready' and coord['revision']==record['revision']
                reason='Current work-ready revision' if admit else 'Superseded work-ready revision, no inference'
            elif typ=='cancel' and not self.is_lead:
                step=self.db.execute('SELECT * FROM assignment WHERE id=?',(coord['taskId'],)).fetchone()
                if (not step or event['author']!=self.lead or event.get('source')!=step['event']
                        or coord['revision']!=step['revision']):raise ValueError('Cancellation must address the original assignment')
                if step['state'] not in ('done','cancelled'):
                    self.db.execute("UPDATE assignment SET state='cancel_requested' WHERE id=?",(step['id'],))
                    admit=True;reason='Lead cancellation of this original assignment; reconcile effects and report actual stop'
            self.db.execute('INSERT INTO input(event,digest,canonical,work,admit,reason) VALUES(?,?,?,?,?,?)',
                (event['id'],fingerprint,encoded(event),work,int(admit),reason))
        return admit,reason

    def admitted(self,event,turn):
        row=self.db.execute('SELECT * FROM input WHERE event=?',(event['id'],)).fetchone()
        if not row or not row['admit']:raise ValueError('Input has no native admission decision')
        with self.db:
            if row['turn'] and row['turn']!=turn:raise ValueError('Original input native turn changed')
            self.db.execute('UPDATE input SET turn=? WHERE event=?',(turn,event['id']))
            if row['work']:
                record=self.work(row['work'])
                self.db.execute('INSERT INTO turn_work VALUES(?,?,?) ON CONFLICT DO NOTHING',(turn,record['id'],record['progress_revision']))
                self.db.execute("UPDATE work SET state='working' WHERE id=? AND state='ready'",(record['id'],))

    def queue(self,key,payload):
        wire=encoded(payload);old=self.db.execute('SELECT payload FROM outbox WHERE id=?',(key,)).fetchone()
        if old and old['payload']!=wire:raise ValueError('Original communication intent changed')
        self.db.execute('INSERT INTO outbox(id,payload) VALUES(?,?) ON CONFLICT DO NOTHING',(key,wire))
        return key

    def delegate(self,work,agent,brief,key,evidence=()):
        if not self.is_lead:raise PermissionError('Only the project lead assigns work')
        record=self.work(work);agent=str(UUID(agent))
        if record['state'] in ('complete','cancelled','paused'):raise ValueError('Original work is stopped or completed')
        if agent==self.agent:raise ValueError('Execute local work directly; do not assign a message to yourself')
        if len(evidence)>8 or any(not isinstance(r,str) or not 1<=len(r)<=256 for r in evidence):raise ValueError('Use bounded evidence references')
        if not isinstance(brief,str) or not brief or len(brief.encode())>2048:raise ValueError('Use one compact assignment, at most2048UTF8 bytes')
        task=str(uuid5(UUID(self.agent),'assignment:'+work+':'+key))
        coord=dict(type='task',taskId=task,revision=1,evidence=list(evidence),originEventId=record['source'])
        args=dict(body=brief,audience='direct' if json.loads(record['human'])['audience']=='direct' else 'room',recipientId=agent,sourceEventId=None,responsePhase='message',coordination=coord)
        with self.db:
            prior=self.db.execute('SELECT * FROM assignment WHERE id=?',(task,)).fetchone()
            if prior and (prior['work'],prior['agent'],prior['brief'])!=(work,agent,brief):raise ValueError('Assignment intent changed')
            self.db.execute("INSERT INTO assignment(id,work,agent,revision,state,brief) VALUES(?,?,?,1,'prepared',?) ON CONFLICT DO NOTHING",(task,work,agent,brief))
            self.queue('assign:'+task,args)
            if not prior:self.db.execute('UPDATE work SET progress_revision=progress_revision+1,no_progress=0 WHERE id=?',(work,))
        return task,'assign:'+task

    def report(self,task,outcome,summary,key,evidence=()):
        step=self.db.execute('SELECT * FROM assignment WHERE id=?',(str(UUID(task)),)).fetchone()
        if not step or step['agent']!=self.agent or not step['source']:raise ValueError('Only the original assigned worker reports this task')
        if outcome not in ('done','progress','blocked','waiting','failed','cancelled'):raise ValueError('Unknown task outcome')
        if not isinstance(summary,str) or not summary.strip() or len(summary.encode())>1024:raise ValueError('Use a concise result, at most1024UTF8 bytes')
        if len(evidence)>8 or any(not isinstance(r,str) or not 1<=len(r)<=256 for r in evidence):raise ValueError('Use bounded evidence references')
        source=json.loads(step['source'])
        args=dict(body=summary,audience=source['audience'],recipientId=source['author'],sourceEventId=source['id'],responsePhase='message',
            coordination=dict(type='result',taskId=step['id'],revision=step['revision'],outcome=outcome,evidence=list(evidence)))
        with self.db:self.queue(key,args)
        return key

    def accepted(self,key,receipt):
        event=receipt['event'];coord=event['data'].get('coordination',{})
        with self.db:
            from .team_dialogue import accepted as dialogue_accepted
            dialogue_accepted(self.db,key,event)
            self.db.execute("UPDATE outbox SET state='accepted',receipt=?,reason=NULL WHERE id=?",(encoded(receipt),key))
            if coord.get('type')=='task':
                self.db.execute("UPDATE assignment SET state='queued',event=? WHERE id=? AND state='prepared'",(event['id'],coord['taskId']))
                step=self.db.execute('SELECT * FROM assignment WHERE id=?',(coord['taskId'],)).fetchone()
                work=self.work(step['work'])
                if work['state'] in ('cancelled','paused'):self.request_cancellation(step)
            if coord.get('type')=='result':
                self.db.execute('UPDATE assignment SET state=? WHERE id=?',(coord['outcome'],coord['taskId']))

    def request_cancellation(self,step):
        if not step['event']:return  # Unknown assignment first reconciles original acceptance.
        coord=dict(type='cancel',taskId=step['id'],revision=step['revision'])
        args=dict(body='Cancel only this original assignment. Stop useful execution safely, reconcile any uncertain external action, and team_report the actual cancelled/result state. Preserve unrelated tasks.',
            audience='room',recipientId=step['agent'],sourceEventId=step['event'],responsePhase='message',coordination=coord)
        self.queue('cancel:'+step['id']+':'+str(step['revision']),args)
        self.db.execute("UPDATE assignment SET state='cancel_requested' WHERE id=?",(step['id'],))

    def disposition(self,work,state,reason):
        if not self.is_lead or state not in ('ready','waiting','paused','cancelled','complete'):
            raise ValueError('Explicit lead disposition required')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError('A short meaningful disposition is required')
        record=self.work(work)
        if record['state'] in ('complete','cancelled') and state!=record['state']:raise ValueError('Stopped work requires new human intent')
        with self.db:
            self.db.execute('UPDATE work SET state=?,reason=?,revision=revision+1 WHERE id=?',(state,reason,work))
            if state in ('cancelled','paused'):
                for step in self.db.execute("SELECT * FROM assignment WHERE work=? AND state NOT IN ('done','cancelled','failed')",(work,)).fetchall():
                    self.request_cancellation(step)

    def ended(self,turn,status):
        """One durable native-end decision. No periodic model polling."""
        with self.db:
            if not self.db.execute('INSERT INTO native_end VALUES(?,?) ON CONFLICT DO NOTHING',(turn,status)).rowcount:return
            rows=self.db.execute('SELECT w.*,t.progress_revision AS started_progress FROM work w JOIN turn_work t ON t.work=w.id WHERE t.turn=?',(turn,)).fetchall()
            for row in rows:
                if row['state'] not in ('working','ready'):continue
                if status=='interrupted':
                    self.db.execute("UPDATE work SET state='paused',reason='Native turn interrupted; no automatic continuation' WHERE id=?",(row['id'],));continue
                pending=self.db.execute("SELECT count(*) FROM assignment WHERE work=? AND state IN ('prepared','queued','ready','progress','waiting','question','cancel_requested')",(row['id'],)).fetchone()[0]
                pending+=self.db.execute("SELECT count(*) FROM team_question_intent i LEFT JOIN team_question q ON q.event=i.event WHERE i.work=? AND (i.event IS NULL OR q.state='pending')",(row['id'],)).fetchone()[0]
                if pending:
                    self.db.execute("UPDATE work SET state='waiting',reason='Waiting for addressed worker results' WHERE id=?",(row['id'],));continue
                if status!='completed':
                    self.db.execute("UPDATE work SET state='fault',reason='Original native turn '+?+'; await scoped runtime recovery' WHERE id=?",(status,row['id']));continue
                attempts=0 if row['progress_revision']>row['started_progress'] else row['no_progress']+1
                if attempts>1:
                    self.db.execute("UPDATE work SET state='fault',no_progress=?,reason='Lead ended twice without material progress or an explicit disposition' WHERE id=?",(attempts,row['id']));continue
                revision=row['revision']+1
                self.db.execute("UPDATE work SET state='ready',revision=?,no_progress=? WHERE id=?",(revision,attempts,row['id']))
                self.ready_event(row['id'],revision)

    def snapshot(self, *, work_id=None, after=0):
        if not isinstance(after,int) or isinstance(after,bool) or after<0:
            raise ValueError('Work cursor must be a nonnegative integer')
        selected=self.work(work_id) if work_id else None
        rows=self.db.execute("SELECT rowid AS cursor,id,source,state,revision,reason,no_progress FROM work WHERE state NOT IN ('complete','cancelled') AND rowid>? ORDER BY rowid LIMIT 21",(after,)).fetchall()
        result=dict(version=1,roomId=self.room,leadAgentId=self.lead,role='lead' if self.is_lead else 'worker',
            work=[dict(r)for r in rows[:20]],nextCursor=rows[19]['cursor'] if len(rows)>20 else None,
            outstandingCount=self.db.execute("SELECT count(*) FROM work WHERE state NOT IN ('complete','cancelled')").fetchone()[0])
        if selected:
            result['originalWork']={**selected,'human':json.loads(selected['human'])}
            query="SELECT id,work,agent,revision,state,event FROM assignment WHERE work=? ORDER BY rowid LIMIT 51"
            steps=self.db.execute(query,(selected['id'],)).fetchall()
        else:
            steps=self.db.execute("SELECT id,work,agent,revision,state,event FROM assignment WHERE state NOT IN ('done','cancelled') ORDER BY rowid LIMIT 51").fetchall()
        result['assignments']=[dict(r)for r in steps[:50]]
        result['assignmentsTruncated']=len(steps)>50
        return result
