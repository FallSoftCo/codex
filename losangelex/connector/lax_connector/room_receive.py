"""Durable canonical input receipt, independent of execution/work ownership.

This is the communication receive journal, not proof of native commitment.
A native RPC acknowledgement alone is insufficient to advance to committed.
Unknown handoffs are reconciled by the original ID; they are never resubmitted.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path


class ReceiveConflict(ValueError):
    pass


class RoomReceiveJournal:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS room_input (
            authority TEXT NOT NULL, agent TEXT NOT NULL, event TEXT NOT NULL,
            thread TEXT NOT NULL, seq INTEGER NOT NULL, digest TEXT NOT NULL,
            payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'received',
            acknowledgement TEXT, commitment TEXT,
            PRIMARY KEY(authority,agent,event),
            CHECK(state IN ('received','handoff','acknowledged','committed'))
        )''')
        self.db.commit()

    def close(self):
        self.db.close()

    def stage(self, *, authority, agent, event, thread, seq, payload):
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            raise ValueError('Canonical nonnegative sequence required')
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        with self.db:
            self.db.execute('''INSERT INTO room_input
                (authority,agent,event,thread,seq,digest,payload)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(authority,agent,event) DO NOTHING''',
                (authority,agent,event,thread,seq,fingerprint,encoded))
            row = self.read(authority, agent, event)
            if (row['thread'],row['seq'],row['digest']) != (thread,seq,fingerprint):
                raise ReceiveConflict('Original room input identity or contents changed')
        return row

    def read(self, authority, agent, event):
        row = self.db.execute('SELECT * FROM room_input WHERE authority=? AND agent=? AND event=?',
                              (authority,agent,event)).fetchone()
        return dict(row) if row else None

    def begin_handoff(self, authority, agent, event):
        # Commit before RPC; a second process or restart cannot race a resend.
        with self.db:
            return self.db.execute('''UPDATE room_input SET state='handoff'
                WHERE authority=? AND agent=? AND event=? AND state='received' ''',
                (authority,agent,event)).rowcount == 1

    def acknowledge(self, authority, agent, event, response):
        encoded = json.dumps(response, sort_keys=True, separators=(',', ':'))
        with self.db:
            row = self.read(authority,agent,event)
            if row is None or row['state'] == 'received':
                raise ReceiveConflict('No original native handoff')
            if row['acknowledgement'] is not None:
                if row['acknowledgement'] != encoded:
                    raise ReceiveConflict('Native acknowledgement changed')
                return
            self.db.execute('''UPDATE room_input SET acknowledgement=?,
                state=CASE WHEN state='committed' THEN state ELSE 'acknowledged' END
                WHERE authority=? AND agent=? AND event=?''', (encoded,authority,agent,event))

    def pending(self, authority, agent, limit=100):
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1 <= limit <= 1000:
            raise ValueError('Bounded page required')
        return [dict(row) for row in self.db.execute('''SELECT * FROM room_input
            WHERE authority=? AND agent=? AND state!='committed'
            ORDER BY seq,event LIMIT ?''',(authority,agent,limit))]


class NativeReceiptUnresolved(RuntimeError):
    """Original handoff needs native evidence; never a signal to resend."""


async def receive_human(journal, rpc, event, *, authority_id, agent_id, thread_id):
    from .room_input import human_input
    payload = human_input(event,authority_id=authority_id,agent_id=agent_id,thread_id=thread_id)
    row = journal.stage(authority=authority_id,agent=agent_id,event=event['id'],
                        thread=thread_id,seq=event['seq'],payload=payload)
    if row['acknowledgement'] is not None:
        return json.loads(row['acknowledgement'])
    if not journal.begin_handoff(authority_id,agent_id,event['id']):
        raise NativeReceiptUnresolved('Reconcile original native room input '+event['id'])
    # Cancellation, process death and transport errors deliberately leave the
    # write-ahead handoff intact. They do not prove that native rejected input.
    response = await rpc.call('turn/start',payload)
    journal.acknowledge(authority_id,agent_id,event['id'],response)
    return response
