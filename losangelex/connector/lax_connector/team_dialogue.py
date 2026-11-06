"""Terse addressed question/reply mailboxes; reading is not model admission."""
import json
from uuid import UUID

SCHEMA='''
CREATE TABLE IF NOT EXISTS team_question_intent (
 key TEXT PRIMARY KEY,task TEXT NOT NULL,work TEXT,room TEXT NOT NULL,counterpart TEXT NOT NULL,event TEXT);
CREATE TABLE IF NOT EXISTS team_question (
 event TEXT PRIMARY KEY,task TEXT NOT NULL,work TEXT,direction TEXT NOT NULL,
 canonical TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',answer TEXT);
'''


def accepted(db,key,event):
    coord=event['data'].get('coordination',{})
    if coord.get('type')=='question':
        intent=db.execute('SELECT * FROM team_question_intent WHERE key=?',(key,)).fetchone()
        if intent:
            db.execute('UPDATE team_question_intent SET event=? WHERE key=?',(event['id'],key))
            db.execute("INSERT INTO team_question(event,task,work,direction,canonical) VALUES(?,?,?,'out',?) ON CONFLICT DO NOTHING",
                (event['id'],coord['taskId'],intent['work'],json.dumps(event,sort_keys=True)))
    elif coord.get('type')=='answer':
        db.execute("UPDATE team_question SET state='answered',answer=? WHERE event=? AND direction='in'",(json.dumps(event,sort_keys=True),event['source']))


def incoming(db,event,work=None):
    coord=event['data']['coordination']
    db.execute("INSERT INTO team_question(event,task,work,direction,canonical) VALUES(?,?,?,'in',?) ON CONFLICT DO NOTHING",
        (event['id'],coord['taskId'],work,json.dumps(event,sort_keys=True)))


def answer_received(db,event):
    row=db.execute("SELECT * FROM team_question WHERE event=? AND direction='out'",(event.get('source'),)).fetchone()
    if not row:raise ValueError('Original outgoing question acceptance must be reconciled before its answer')
    source=json.loads(row['canonical']);coord=event['data']['coordination']
    if source['recipient']!=event['author'] or source['author']!=event['recipient'] or source['data']['coordination']['taskId']!=coord['taskId']:
        raise ValueError('Answer belongs to another question/counterpart')
    if row['state']!='pending':return row,False
    db.execute("UPDATE team_question SET state='answered',answer=? WHERE event=?",(json.dumps(event,sort_keys=True),row['event']))
    return row,True


def answer_payload(db,identity,summary):
    row=db.execute("SELECT * FROM team_question WHERE event=? AND direction='in'",(str(UUID(identity)),)).fetchone()
    if not row:raise ValueError('Unknown addressed peer question')
    if not isinstance(summary,str) or not summary.strip() or len(summary.encode())>1024:raise ValueError('Use a concise answer, at most1024UTF8 bytes')
    source=json.loads(row['canonical']);coord=source['data']['coordination']
    return dict(body=summary,audience=source['audience'],recipientId=source['author'],sourceEventId=source['id'],responsePhase='message',
        coordination=dict(type='answer',taskId=coord['taskId'],revision=coord['revision']))


def dependencies(db, *, work=None, task=None):
    """Accepted questions and original sends awaiting transport reconciliation.

    A rejected intent cannot become an outstanding reply on either side.
    """
    if (work is None)==(task is None):raise ValueError('Select one original work or assignment')
    field='work' if work is not None else 'task';identity=work if work is not None else task
    accepted=db.execute("SELECT count(*) FROM team_question WHERE "+field+"=? AND direction='out' AND state='pending'",(identity,)).fetchone()[0]
    admitting=db.execute("SELECT count(*) FROM team_question_intent i JOIN outbox o ON o.id=i.key WHERE i."+field+"=? AND i.event IS NULL AND o.state='ready'",(identity,)).fetchone()[0]
    return dict(accepted=accepted,admitting=admitting)
