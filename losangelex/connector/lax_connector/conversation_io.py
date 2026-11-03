"""Indexed causal input receipts and native final-message delivery intent.

Adapter I/O only: no task scheduler, inferred execution state or model polling.
Hollywood remains the canonical room history and native Core owns its turns.
"""
from .runtime_files import state_directory
import json
import os
import sqlite3
from pathlib import Path
from uuid import UUID


def reply_expected(event):
    return (event.get('data', {}).get('authorKind') == 'human'
            or event.get('kind') == 'request'
            or bool(event.get('data', {}).get('expectsReply')))


class ConversationIO:
    def __init__(self, path, *, authority, agent, thread):
        path = Path(path)
        state_directory(path.parent, parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS binding(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS input_source(
                ordinal INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT UNIQUE NOT NULL,
                canonical TEXT NOT NULL, room TEXT NOT NULL, reply_scope TEXT NOT NULL, turn TEXT);
            CREATE INDEX IF NOT EXISTS input_turn ON input_source(turn, room, ordinal);
            CREATE TABLE IF NOT EXISTS publication(
                turn TEXT NOT NULL, source TEXT, key TEXT NOT NULL, room TEXT NOT NULL,
                state TEXT NOT NULL, PRIMARY KEY(turn,key));
            CREATE INDEX IF NOT EXISTS publication_source ON publication(turn,source,state);
            CREATE TABLE IF NOT EXISTS native_end(turn TEXT PRIMARY KEY, phase TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS output(
                item TEXT PRIMARY KEY, turn TEXT NOT NULL, body TEXT NOT NULL,
                phase TEXT NOT NULL, state TEXT NOT NULL, reason TEXT);
            CREATE INDEX IF NOT EXISTS output_state ON output(state);
        ''')
        self.binding = {'authority': str(UUID(authority)), 'agent': str(UUID(agent)), 'thread': thread}
        encoded = json.dumps(self.binding, sort_keys=True)
        with self.db:
            self.db.execute('INSERT INTO binding VALUES(1,?) ON CONFLICT(id) DO NOTHING', (encoded,))
            if self.db.execute('SELECT value FROM binding WHERE id=1').fetchone()['value'] != encoded:
                raise ValueError('Conversation I/O belongs to another native owner')
        self._migrate_reply_sources()
        from .room_reply_state import SCHEMA
        from .room_reply_receipts import SCHEMA as RECEIPT_SCHEMA
        with self.db:
            self.db.executescript(SCHEMA)
            self.db.executescript(RECEIPT_SCHEMA)

    def _migrate_reply_sources(self):
        # Additive, backward-readable adapter metadata. Bounded backfill avoids
        # decoding an entire long-lived agent's input history into memory.
        with self.db:
            columns = {r['name'] for r in self.db.execute('PRAGMA table_info(input_source)')}
            if 'reply_eligible' not in columns:
                self.db.execute('ALTER TABLE input_source ADD COLUMN reply_eligible INTEGER')
            self.db.execute('CREATE INDEX IF NOT EXISTS input_reply_turn ON input_source(turn,reply_eligible,room,ordinal)')
            self.db.execute('CREATE INDEX IF NOT EXISTS input_source_unclassified ON input_source(ordinal) WHERE reply_eligible IS NULL')
            self.db.execute('''CREATE TABLE IF NOT EXISTS delivery_repair(
                item TEXT PRIMARY KEY, previous_state TEXT NOT NULL,
                previous_reason TEXT NOT NULL, source TEXT NOT NULL,
                repair_version INTEGER NOT NULL)''')
        while True:
            rows = self.db.execute('SELECT event,canonical FROM input_source WHERE reply_eligible IS NULL LIMIT 128').fetchall()
            if not rows:
                break
            with self.db:
                self.db.executemany('UPDATE input_source SET reply_eligible=? WHERE event=? AND reply_eligible IS NULL',
                    [(int(reply_expected(json.loads(row['canonical']))), row['event']) for row in rows])

    def recover_passive_suppression(self, item, expected_source):
        """Audited repair of ONE known completed final; never sweep old history.

        The caller supplies the original native item and canonical source. Normal
        startup only migrates source metadata; it does not reopen terminal output.
        The ordinary durable publisher reconciles any existing publication ledger.
        """
        expected_source = str(UUID(expected_source))
        if not isinstance(item, str) or not 1 <= len(item) <= 256:
            raise ValueError('Exact original native final item required')
        with self.db:
            row = self.db.execute("""SELECT o.item,o.turn,o.state,o.reason,n.phase AS native_phase
                FROM output o JOIN native_end n ON n.turn=o.turn WHERE o.item=?""", (item,)).fetchone()
            if row is None:
                raise ValueError('Original completed native final unavailable')
            source = self.source(row['turn'])
            if not source or not reply_expected(source) or source['id'] != expected_source:
                raise ValueError('Original reply-eligible canonical source differs or is ambiguous')
            prior = self.db.execute('SELECT * FROM delivery_repair WHERE item=?', (item,)).fetchone()
            if prior:
                if prior['source'] != expected_source or prior['repair_version'] != 1:
                    raise ValueError('Original final recovery belongs to another source')
                return {'item': item, 'source': expected_source, 'state': row['state'], 'reconciled': True}
            if (row['state'] != 'suppressed' or row['reason'] != 'Peer publication remains explicit'
                    or row['native_phase'] != 'completed'):
                raise ValueError('Only the known completed passive-source suppression is repairable')
            self.db.execute('INSERT INTO delivery_repair VALUES(?,?,?,?,1)',
                (item, row['state'], row['reason'], expected_source))
            self.db.execute("""UPDATE output SET state='queued',reason='Recovered original request after passive input'
                WHERE item=? AND state='suppressed' AND reason='Peer publication remains explicit' """, (item,))
            return {'item': item, 'source': expected_source, 'state': 'queued', 'reconciled': False}

    def stage(self, event):
        if (event.get('authority') != self.binding['authority']
                or self.binding['agent'] not in event.get('data', {}).get('conversationRecipients', [])
                or event.get('data', {}).get('authorKind') not in {'human', 'agent'}):
            raise ValueError('Canonical native input scope required')
        identity = str(UUID(event['id']))
        encoded = json.dumps(event, sort_keys=True)
        scope = json.dumps([event['room'], event['audience'],
                            event['author'] if event['audience'] == 'direct' else None])
        with self.db:
            old = self.db.execute('SELECT canonical FROM input_source WHERE event=?', (identity,)).fetchone()
            if old and old['canonical'] != encoded:
                raise ValueError('Original input scope changed')
            self.db.execute('''INSERT INTO input_source(event,canonical,room,reply_scope,reply_eligible)
                VALUES(?,?,?,?,?) ON CONFLICT(event) DO NOTHING''',
                            (identity, encoded, event['room'], scope, int(reply_expected(event))))

    def bind(self, event, reply):
        turn = (reply.get('turn') or {}).get('id')
        if not isinstance(turn, str) or not turn:
            raise ValueError('Native turn acknowledgement required')
        with self.db:
            old = self.db.execute('SELECT turn FROM input_source WHERE event=?', (event['id'],)).fetchone()
            if not old or old['turn'] is not None and old['turn'] != turn:
                raise ValueError('Original native turn receipt unavailable or changed')
            self.db.execute('UPDATE input_source SET turn=? WHERE event=?', (turn, event['id']))
        return turn

    def source(self, turn, room=None):
        query, args = 'turn=?', [turn]
        if room is not None:
            query += ' AND room=?'
            args.append(room)
        # Context-only peer traffic cannot replace or make ambiguous an owed
        # answer. Keep the passive-only fallback so ordinary chatter stays silent.
        if self.db.execute('SELECT 1 FROM input_source WHERE ' + query + ' AND reply_eligible=1 LIMIT 1', args).fetchone():
            query += ' AND reply_eligible=1'
        count = self.db.execute('SELECT count(DISTINCT reply_scope) AS n FROM input_source WHERE ' + query,
                                args).fetchone()['n']
        if count != 1:
            return None
        row = self.db.execute('SELECT canonical FROM input_source WHERE ' + query +
                              ' ORDER BY ordinal DESC LIMIT 1', args).fetchone()
        return json.loads(row['canonical'])

    def primary(self, turn):
        row = self.db.execute('SELECT canonical FROM input_source WHERE turn=? ORDER BY ordinal LIMIT 1',
                              (turn,)).fetchone()
        return json.loads(row['canonical']) if row else None

    def input_event(self, event):
        """Read one retained canonical input, never infer or widen its audience."""
        row = self.db.execute('SELECT canonical FROM input_source WHERE event=?',
                              (str(UUID(event)),)).fetchone()
        return json.loads(row['canonical']) if row else None

    def rooms(self, turn):
        return {x['room'] for x in self.db.execute('SELECT DISTINCT room FROM input_source WHERE turn=?', (turn,))}

    def observe_own_reply(self, event):
        from .room_reply_receipts import observe
        return observe(self, event)

    def publication(self, turn, source, key, room, state, *, phase=None, event_id=None):
        if state not in {'attempting', 'accepted', 'rejected'}:
            raise ValueError('Actual publication receipt state required')
        if phase not in (None, 'answer', 'blocked'):
            raise ValueError('Exact final response phase required')
        with self.db:
            if event_id is not None:
                old_event = self.db.execute('SELECT event FROM reply_publication_event WHERE turn=? AND key=?', (turn,key)).fetchone()
                if old_event and old_event['event'] != event_id:
                    raise ValueError('Original publication canonical event changed')
                self.db.execute('INSERT INTO reply_publication_event VALUES(?,?,?) ON CONFLICT DO NOTHING', (turn,key,event_id))
            if phase is not None:
                prior = self.db.execute('SELECT phase FROM reply_publication_phase WHERE turn=? AND key=?', (turn,key)).fetchone()
                if prior and prior['phase'] != phase:
                    raise ValueError('Original publication response phase changed')
                self.db.execute('INSERT INTO reply_publication_phase VALUES(?,?,?) ON CONFLICT DO NOTHING', (turn,key,phase))
            old = self.db.execute('SELECT state FROM publication WHERE turn=? AND key=?', (turn, key)).fetchone()
            if old and old['state'] == 'accepted':
                return
            self.db.execute('''INSERT INTO publication VALUES(?,?,?,?,?) ON CONFLICT(turn,key)
                DO UPDATE SET source=excluded.source,state=excluded.state''', (turn, source, key, room, state))

    def publications(self, turn, source):
        return [dict(x) for x in self.db.execute('SELECT * FROM publication WHERE turn=? AND source=?', (turn, source))]

    def final(self, turn, item, body, phase='answer'):
        if not body.strip():
            return
        with self.db:
            old = self.db.execute('SELECT turn,body,phase FROM output WHERE item=?', (item,)).fetchone()
            if old and (old['turn'], old['body'], old['phase']) != (turn, body, phase):
                raise ValueError('Original native final changed')
            ended = self.db.execute('SELECT 1 FROM native_end WHERE turn=?', (turn,)).fetchone()
            self.db.execute('''INSERT INTO output(item,turn,body,phase,state) VALUES(?,?,?,?,?)
                ON CONFLICT(item) DO NOTHING''', (item, turn, body, phase, 'queued' if ended else 'staged'))

    def ended(self, turn, phase):
        with self.db:
            self.db.execute('INSERT INTO native_end VALUES(?,?) ON CONFLICT(turn) DO NOTHING', (turn, phase))
            self.db.execute("UPDATE output SET state='queued' WHERE turn=? AND state='staged'", (turn,))

    def pending(self):
        from .room_reply_state import AMBIGUOUS
        return [dict(x) for x in self.db.execute("""SELECT o.* FROM output o
            LEFT JOIN reply_delivery_hold h ON h.item=o.item
            WHERE o.state='queued' AND (h.item IS NULL OR h.reason!=?) ORDER BY o.rowid LIMIT 32""", (AMBIGUOUS,))]

    def hold_ambiguous_final(self, row):
        from .room_reply_state import hold
        hold(self.db, row)

    def reply_status(self, room, *, after=0, limit=100, recent=True):
        from .room_reply_state import report
        return report(self, str(UUID(room)), after=after, limit=limit, recent=recent)

    def unfinished(self):
        return [x['turn'] for x in self.db.execute("SELECT DISTINCT turn FROM output WHERE state='staged' LIMIT 100")]

    def finish(self, item, state, reason=None):
        if state not in {'accepted', 'suppressed', 'blocked'}:
            raise ValueError('Final delivery outcome required')
        with self.db:
            self.db.execute('UPDATE output SET state=?,reason=? WHERE item=?', (state, reason, item))

    def close(self):
        self.db.close()
