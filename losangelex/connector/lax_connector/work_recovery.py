"""Durable, source-bound recovery; timers perform metadata checks, never polling turns."""
import hashlib
import json
import time

TRANSIENT={'rateLimitExceeded','flexUnavailable','serverOverloaded','httpConnectionFailed','responseStreamConnectionFailed','responseStreamDisconnected','responseTooManyFailedAttempts','internalServerError'}


def category(error):
    info=(error or {}).get('codexErrorInfo');name=info if isinstance(info,str) else next(iter(info),None) if isinstance(info,dict) else None
    details=info.get(name,{}) if isinstance(info,dict) else {};status=details.get('httpStatusCode') if isinstance(details,dict) else None
    if status is not None and status not in (408,425,429,500,502,503,504):return 'blocked'
    return 'transient' if name in TRANSIENT else 'blocked'


class WorkRecovery:
    def __init__(self,ledger):
        self.ledger=ledger;self.db=ledger.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS work_recovery(work TEXT,turn TEXT,kind TEXT,state TEXT,due REAL,attempt INTEGER,progress INTEGER,error TEXT,PRIMARY KEY(work,turn));
          CREATE INDEX IF NOT EXISTS recovery_due ON work_recovery(state,due);
          CREATE TABLE IF NOT EXISTS recovery_observation(id INTEGER PRIMARY KEY,work TEXT,turn TEXT,observed REAL,body TEXT);
        ''')

    def schedule(self,work,turn,kind,error=None,now=None):
        now=time.time() if now is None else now;row=self.ledger.work(work)
        if row['state'] in ('complete','cancelled','paused'):return
        previous=self.db.execute('SELECT * FROM work_recovery WHERE work=? AND progress=? ORDER BY rowid DESC LIMIT 1',(work,row['progress_revision'])).fetchone()
        # One diagnostic model opportunity for each genuinely changed progress
        # frontier. More unchanged ends stay inspectable, without model loops.
        blocked=kind=='blocked' or kind=='stalled' and self.db.execute("SELECT 1 FROM work_recovery WHERE work=? AND progress=? AND kind='stalled' LIMIT 1",(work,row['progress_revision'])).fetchone()
        attempt=previous['attempt']+1 if previous else 0
        delay=min(3600,30*2**min(attempt,7))
        jitter=.9+int(hashlib.sha256((work+turn).encode()).hexdigest()[:4],16)/65535*.2
        state='blocked' if blocked else 'waiting';reason='Recovery needs a changed dependency or explicit repair' if blocked else 'Waiting for diagnosed recovery'
        self.db.execute("UPDATE work_recovery SET state='superseded' WHERE work=? AND turn!=? AND state='waiting'",(work,turn))
        self.db.execute('INSERT INTO work_recovery VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',(work,turn,kind,state,now+delay*jitter,attempt,row['progress_revision'],json.dumps(error or {},sort_keys=True)))
        self.db.execute('UPDATE work SET state=?,reason=? WHERE id=?',('fault' if blocked else 'recovering',reason,work))

    def next_due(self):
        row=self.db.execute("SELECT min(r.due) FROM work_recovery r JOIN work w ON w.id=r.work WHERE r.state='waiting' AND w.state='recovering'").fetchone()
        return row[0]

    def snapshot(self,work):
        rows=self.db.execute('SELECT turn,kind,state,due,attempt,error FROM work_recovery WHERE work=? ORDER BY rowid DESC LIMIT 5',(work,)).fetchall()
        observations=self.db.execute('SELECT observed,body FROM recovery_observation WHERE work=? ORDER BY id DESC LIMIT 3',(work,)).fetchall()
        return {'attempts':[dict(r) for r in rows],'diagnostics':[{'observed':r['observed'],**json.loads(r['body'])} for r in observations]}

    async def inspect_due(self,owner,now=None):
        from .room_session_inspect import journal_counts
        now=time.time() if now is None else now
        rows=self.db.execute("SELECT r.* FROM work_recovery r JOIN work w ON w.id=r.work WHERE r.state='waiting' AND w.state='recovering' AND r.due<=? ORDER BY r.due LIMIT 4",(now,)).fetchall()
        for row in rows:
            proof={'nativeThreadId':owner.thread,'failedTurn':row['turn'],'eligible':False}
            try:
                status=(await owner.rpc.call('thread/read',{'threadId':owner.thread,'includeTurns':False}))['thread']
                proof['nativeStatus']=status['status'];proof['io']=journal_counts(owner.config)
                bg=await owner.rpc.call('thread/backgroundTerminals/list',{'threadId':owner.thread,'limit':100})
                proof['backgroundCommands']=len(bg.get('data',bg.get('terminals',[])));proof['backgroundTruncated']=bool(bg.get('nextCursor'))
                page=await owner.rpc.call('thread/turns/list',{'threadId':owner.thread,'limit':1});latest=page.get('data',[])
                proof['latestTurn']={k:latest[0].get(k) for k in ('id','status','error')} if latest else None
                proof['pendingAttention']=bool(owner.attention.pending);proof['dependencies']=self.ledger.dependencies(row['work'])
                proof['eligible']=(status['id']==owner.thread and status['status']['type'] in ('idle','systemError') and not any(proof['io'].values()) and not proof['backgroundCommands'] and not proof['backgroundTruncated'] and not proof['pendingAttention'] and bool(latest) and latest[0]['id']==row['turn'] and latest[0]['status'] in ('completed','failed') and not any(proof['dependencies'][k] for k in ('assignments','questions','admitting')))
                if row['kind']=='transient' and latest:proof['eligible']=proof['eligible'] and category(latest[0].get('error'))=='transient'
            except Exception as error:
                proof['readErrorType']=type(error).__name__  # no secrets or raw transport exceptions
            with self.db:
                current=self.db.execute('SELECT state FROM work_recovery WHERE work=? AND turn=?',(row['work'],row['turn'])).fetchone()
                work=self.ledger.work(row['work'])
                if not current or current['state']!='waiting' or work['state']!='recovering':continue
                self.db.execute('INSERT INTO recovery_observation(work,turn,observed,body) VALUES(?,?,?,?)',(row['work'],row['turn'],now,json.dumps(proof,sort_keys=True)))
                if proof['eligible']:
                    revision=work['revision']+1;reason=('Diagnose the retained no-progress turns, inspect acceptance/evidence and change the approach before useful continuation. Do not repeat unchanged steps.' if row['kind']=='stalled' else 'Confirmed terminal transient failure; resume retained original context and checkpoints. Reconcile external effects before any action; never resend the original request.')
                    self.db.execute("UPDATE work SET state='ready',revision=?,reason=? WHERE id=?",(revision,reason,row['work']))
                    self.ledger.ready_event(row['work'],revision)
                    self.db.execute("UPDATE work_recovery SET state='released' WHERE work=? AND turn=?",(row['work'],row['turn']))
                else:
                    attempt=row['attempt']+1;delay=min(3600,30*2**min(attempt,7))
                    # Native health/read checks back off durably. They do not
                    # start a model, clear stops, or replay an unknown delivery.
                    self.db.execute('UPDATE work_recovery SET due=?,attempt=? WHERE work=? AND turn=?',(now+delay,attempt,row['work'],row['turn']))
