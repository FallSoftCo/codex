"""Current obligations, not historical messages, justify an autonomous wait.

One original work ledger owns typed wait bindings and durable coverage. Native
execution, publication reconciliation and completion verification keep their
existing owners; this module never starts a model or republishes human input.
"""
import json
import time

AUTOMATIC_WAITS=('Waiting for addressed worker results','Waiting for original communication delivery')


class WorkObligations:
    def __init__(self,ledger):
        self.ledger=ledger;self.db=ledger.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS work_wait(work TEXT PRIMARY KEY,kind TEXT,reference TEXT,state TEXT,revision INTEGER);
          CREATE TABLE IF NOT EXISTS human_wait_intent(key TEXT PRIMARY KEY,work TEXT,turn TEXT,revision INTEGER,state TEXT);
          CREATE TABLE IF NOT EXISTS work_coverage(work TEXT PRIMARY KEY,state TEXT,body TEXT,observed REAL);
        ''')
        # One conservative migration of the old explicit human-input state.
        # Automatic peer waits do not inherit all historical blocked messages.
        with self.db:
            for row in self.db.execute("SELECT * FROM work WHERE state='waiting' AND NOT EXISTS(SELECT 1 FROM work_wait b WHERE b.work=work.id)").fetchall():
                if row['reason'] in AUTOMATIC_WAITS:kind,ref='peer',None
                else:
                    sent=self.db.execute("SELECT id FROM outbox WHERE state='accepted' AND json_extract(payload,'$.sourceEventId')=? AND json_extract(payload,'$.responsePhase')='blocked' ORDER BY rowid DESC LIMIT 1",(row['source'],)).fetchone()
                    kind,ref=('human',sent['id']) if sent else ('unresolved',row['reason'])
                self.db.execute('INSERT INTO work_wait VALUES(?,?,?, ?,?)',(row['id'],kind,ref,'active',row['revision']))

    def references(self,work):
        rows=[dict(r) for r in self.db.execute("SELECT id,agent,event,state,revision FROM assignment WHERE work=? AND event IS NOT NULL AND state IN ('queued','ready','progress','waiting','question','cancel_requested')",(work,))]
        questions=[dict(r) for r in self.db.execute("SELECT event,task FROM team_question WHERE work=? AND direction='out' AND state='pending'",(work,))]
        sends=[dict(r) for r in self.db.execute("SELECT o.id,o.attempted FROM outbox o WHERE o.state='ready' AND (EXISTS(SELECT 1 FROM assignment a WHERE a.work=? AND a.event IS NULL AND o.id='assign:'||a.id) OR EXISTS(SELECT 1 FROM team_question_intent i WHERE i.work=? AND i.event IS NULL AND i.key=o.id))",(work,work))]
        wait=self.db.execute("SELECT kind,reference,revision FROM work_wait WHERE work=? AND state='active'",(work,)).fetchone()
        return dict(assignments=rows,questions=questions,admitting=sends,wait=dict(wait)if wait else None)

    def human_count(self,work):
        return self.db.execute("SELECT count(*) FROM work_wait w JOIN outbox o ON o.id=w.reference WHERE w.work=? AND w.kind='human' AND w.state='active' AND o.state='accepted'",(work,)).fetchone()[0]

    def release(self,work):
        # Releasing a wait to do independent work does not claim the old
        # question was answered. The original reply and intent remain intact.
        self.db.execute("UPDATE work_wait SET state='released' WHERE work=? AND state='active'",(work,))

    def bind_peer_wait(self,work):
        refs=self.references(work)
        if not any(refs[k] for k in ('assignments','questions','admitting')):
            raise ValueError('No current peer or unsettled communication exists to await')
        self.db.execute("INSERT INTO work_wait VALUES(?,'peer',?,'active',?) ON CONFLICT(work) DO UPDATE SET kind='peer',reference=excluded.reference,state='active',revision=excluded.revision",(work,json.dumps({k:v for k,v in refs.items()if k!='wait'},sort_keys=True),self.ledger.work(work)['revision']))

    def human_intent(self,key,work,turn):
        self.db.execute("INSERT INTO human_wait_intent VALUES(?,?,?,?,'pending') ON CONFLICT DO NOTHING",(key,work,turn,self.ledger.work(work)['revision']))

    def accepted(self,key):
        intent=self.db.execute("SELECT * FROM human_wait_intent WHERE key=? AND state='pending'",(key,)).fetchone()
        if not intent:return
        row=self.ledger.work(intent['work'])
        self.db.execute("UPDATE human_wait_intent SET state='accepted' WHERE key=?",(key,))
        if row['state'] in ('complete','cancelled','paused') or row['revision']!=intent['revision']:return
        self.db.execute("INSERT INTO work_wait VALUES(?,'human',?,'active',?) ON CONFLICT(work) DO UPDATE SET kind='human',reference=excluded.reference,state='active',revision=excluded.revision",(row['id'],key,row['revision']+1))
        self.db.execute("UPDATE work SET state='waiting',reason='Human response needs_input',revision=revision+1 WHERE id=?",(row['id'],))

    def reconcile(self):
        if not self.ledger.is_lead:return
        with self.db:
            # Accepted original sends can survive a crash before their local
            # post-ACK handling. Reconcile the same intent, never send again.
            for row in self.db.execute("SELECT i.key FROM human_wait_intent i JOIN outbox o ON o.id=i.key WHERE i.state='pending' AND o.state='accepted'").fetchall():self.accepted(row['key'])
            for row in self.db.execute("SELECT * FROM work WHERE state NOT IN ('complete','cancelled')").fetchall():
                refs=self.references(row['id']);wait=refs['wait'];status=row['state']
                if status=='waiting' and wait and wait['kind']=='peer' and not any(refs[k] for k in ('assignments','questions','admitting')):
                    end=self.db.execute("SELECT e.turn,e.status FROM turn_work t JOIN native_end e ON e.turn=t.turn WHERE t.work=? ORDER BY t.rowid DESC LIMIT 1",(row['id'],)).fetchone()
                    if end and end['status']=='completed':
                        prior=self.db.execute('SELECT state FROM work_recovery WHERE work=? AND turn=?',(row['id'],end['turn'])).fetchone()
                        if not prior:
                            self.ledger.recovery.schedule(row['id'],end['turn'],'dependency_settled',{'reason':'No current peer dependency remains; retained terminal work needs continuation'})
                            self.release(row['id']);status='recovering';refs=self.references(row['id'])
                coverage=dict(owner=self.ledger.agent,source=row['source'],revision=row['revision'],state=status,dependencies=refs)
                text=json.dumps(coverage,sort_keys=True)
                self.db.execute("INSERT INTO work_coverage VALUES(?,?,?,?) ON CONFLICT(work) DO UPDATE SET state=excluded.state,body=excluded.body,observed=excluded.observed",(row['id'],status,text,time.time()))

    def snapshot(self,work):
        row=self.db.execute('SELECT body,observed FROM work_coverage WHERE work=?',(work,)).fetchone()
        return dict(current=self.references(work),coverage={**json.loads(row['body']),'observedAt':row['observed']}if row else None)
