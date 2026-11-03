"""Durable canonical input receipt, independent of execution/work ownership.

This is the communication receive journal, not proof of native commitment.
A native RPC acknowledgement alone is insufficient to advance to committed.
Unknown handoffs are reconciled by the original ID; they are never resubmitted.
"""
from .runtime_files import state_directory
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import copy


class ReceiveConflict(ValueError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def legacy_content(payload):
    """One reviewed renderer-only field, not a general payload filter.

    Legacy rows have no canonical event copy. Prove equal original delivery
    content/scope before appending a canonical identity; retain the original
    payload/digest/ACK verbatim. All other fields, including author/source and
    audience inside the context, remain exact. The explicit migration basis is
    not a claim that legacy payloads recorded canonical-only fields they lacked.
    """
    value = copy.deepcopy(payload)
    params = value.get('params') if isinstance(value, dict) and 'method' in value else value
    if isinstance(params, dict):
        context = params.get('additionalContext', {}).get('laxRoomMessage')
        if isinstance(context, dict) and context.get('kind') == 'application':
            metadata = json.loads(context['value'])
            if (metadata.get('schema') == 'lax-room-message/v1'
                    and metadata.get('authorKind') == 'human'
                    and isinstance(metadata.get('instruction'), str)):
                metadata.pop('instruction')
                context['value'] = encoded(metadata)
    return encoded(value)


class RoomReceiveJournal:
    def __init__(self, path):
        path = Path(path)
        state_directory(path.parent, parents=True, exist_ok=True)
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
        self.db.execute('''CREATE TABLE IF NOT EXISTS room_input_identity (
            authority TEXT NOT NULL, agent TEXT NOT NULL, event TEXT NOT NULL,
            canonical TEXT NOT NULL, digest TEXT NOT NULL, basis TEXT NOT NULL,
            PRIMARY KEY(authority,agent,event)
        )''')
        self.db.commit()

    def close(self):
        self.db.close()

    def stage(self, *, authority, agent, event, thread, seq, payload, canonical=None):
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            raise ValueError('Canonical nonnegative sequence required')
        rendered = encoded(payload)
        fingerprint = digest(rendered)
        if canonical is not None and (not isinstance(canonical, dict)
                or (canonical.get('authority'), canonical.get('id'), canonical.get('seq')) != (authority, event, seq)):
            raise ReceiveConflict('Canonical event binding differs')
        with self.db:
            inserted = self.db.execute('''INSERT INTO room_input
                (authority,agent,event,thread,seq,digest,payload)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(authority,agent,event) DO NOTHING''',
                (authority,agent,event,thread,seq,fingerprint,rendered)).rowcount == 1
            row = self.read(authority, agent, event)
            if (row['thread'],row['seq']) != (thread,seq) or digest(row['payload']) != row['digest']:
                raise ReceiveConflict('Original room input identity or contents changed')
            identity = self.db.execute('''SELECT * FROM room_input_identity
                WHERE authority=? AND agent=? AND event=?''', (authority,agent,event)).fetchone()
            if canonical is None:
                if identity is not None or row['digest'] != fingerprint:
                    raise ReceiveConflict('Original canonical record or rendered input differs')
            elif identity is not None:
                if (digest(identity['canonical']) != identity['digest']
                        or identity['canonical'] != encoded(canonical)):
                    raise ReceiveConflict('Original canonical event identity or contents changed')
            else:
                if not inserted and legacy_content(json.loads(row['payload'])) != legacy_content(payload):
                    raise ReceiveConflict('Original legacy delivery content or scope changed')
                text = encoded(canonical)
                self.db.execute('''INSERT INTO room_input_identity VALUES(?,?,?,?,?,?)''',
                    (authority,agent,event,text,digest(text),
                     'canonical-event-v1' if inserted else 'legacy-rendered-content-v1'))
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

    def has_unresolved(self,authority,agent):
        return self.db.execute('''SELECT 1 FROM room_input WHERE authority=? AND agent=?
            AND state='handoff' AND acknowledgement IS NULL LIMIT 1''',(authority,agent)).fetchone() is not None


class NativeReceiptUnresolved(RuntimeError):
    """Original handoff needs native evidence; never a signal to resend."""


async def receive_human(journal, rpc, event, *, authority_id, agent_id, thread_id):
    from .room_input import human_input
    payload = human_input(event,authority_id=authority_id,agent_id=agent_id,thread_id=thread_id)
    row = journal.stage(authority=authority_id,agent=agent_id,event=event['id'],
                        thread=thread_id,seq=event['seq'],payload=payload,canonical=event)
    if row['acknowledgement'] is not None:
        return json.loads(row['acknowledgement'])
    if not journal.begin_handoff(authority_id,agent_id,event['id']):
        raise NativeReceiptUnresolved('Reconcile original native room input '+event['id'])
    # Cancellation, process death and transport errors deliberately leave the
    # write-ahead handoff intact. They do not prove that native rejected input.
    response = await rpc.call('turn/start',json.loads(row['payload']))
    journal.acknowledge(authority_id,agent_id,event['id'],response)
    return response
