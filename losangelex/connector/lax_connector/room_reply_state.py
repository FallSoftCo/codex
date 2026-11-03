"""Private per-input response outcomes, not work claims or task completion.

One native turn can contain several rooms and audiences. Its final has no native
source selector. Keep that original output, and expose the exact safe hold rather
than guessing, fan-out, retrying inputs or waking another model.
"""
import hashlib
import json


SCHEMA = '''
CREATE TABLE IF NOT EXISTS reply_publication_phase(
 turn TEXT NOT NULL,key TEXT NOT NULL,phase TEXT NOT NULL,
 PRIMARY KEY(turn,key));
CREATE TABLE IF NOT EXISTS reply_delivery_hold(
 item TEXT PRIMARY KEY,reason TEXT NOT NULL,original_metadata TEXT NOT NULL,
 original_body_sha256 TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reply_publication_source ON publication(source,room,state);
'''

AMBIGUOUS = ('Native final has multiple or missing original reply scopes. '
             'Use separate sourceEventId-addressed answers in the original room/audience; '
             'the retained final is not published or fanned out. Native end is not task completion.')
UNBOUND = ('Native final is awaiting its original input/turn acknowledgement. '
           'Reconcile the original receive/handoff receipt; do not submit another input.')


def hold(db, row):
    """Record transport metadata only; retain queued item/body/phase/turn.

    Existing historical rows are never published, suppressed, selected for a
    source or declared answered by this additive diagnosis. Their previous reason
    is retained. No automatic repair/re-admission of a held final exists.
    """
    reason = AMBIGUOUS if db.execute('SELECT 1 FROM input_source WHERE turn=? LIMIT 1', (row['turn'],)).fetchone() else UNBOUND
    with db:
        db.execute('''INSERT INTO reply_delivery_hold VALUES(?,?,?,?)
            ON CONFLICT(item) DO UPDATE SET reason=excluded.reason''', (row['item'], reason,
            json.dumps({k: row[k] for k in ('turn','phase','state','reason')}, sort_keys=True),
            hashlib.sha256(row['body'].encode()).hexdigest()))
        db.execute("UPDATE output SET reason=? WHERE item=? AND state='queued' AND (reason IS NULL OR reason=?)",
                   (reason, row['item'], UNBOUND))


def report(io, room, *, after=0, limit=100, recent=False):
    """Bounded owner-private projection of exact original receipts; no bodies.

    A reply opportunity is not exclusive room/task ownership. In particular an
    answer becoming available does not assert the user's business work is done.
    Private source metadata must not be broadcast as public room activity.
    """
    if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Bounded original response cursor required')
    rows = io.db.execute('''SELECT i.*,n.phase AS native_phase FROM input_source i
        LEFT JOIN native_end n ON n.turn=i.turn
        WHERE i.room=? AND i.reply_eligible=1 AND i.ordinal>? ORDER BY i.ordinal ''' + ('DESC' if recent else 'ASC') + ' LIMIT ?',
        (room, after, limit + 1)).fetchall()
    outcomes = []
    for row in rows[:limit]:
        source = json.loads(row['canonical'])
        pubs = [dict(p) for p in io.db.execute('''SELECT p.key,p.state,d.phase FROM publication p
            LEFT JOIN reply_publication_phase d ON d.turn=p.turn AND d.key=p.key
            WHERE p.source=? AND p.room=? ORDER BY p.rowid DESC LIMIT 101''', (row['event'], room))]
        accepted = [dict(p) for p in io.db.execute('''SELECT DISTINCT d.phase FROM publication p
            LEFT JOIN reply_publication_phase d ON d.turn=p.turn AND d.key=p.key
            WHERE p.source=? AND p.room=? AND p.state='accepted' ''', (row['event'],room))]
        if accepted:
            # Do not invent a phase for old SDK receipts which did not store it.
            state = ('answer_available' if any(p['phase']=='answer' for p in accepted)
                     else 'blocked_reported' if any(p['phase']=='blocked' for p in accepted)
                     else 'accepted_final_phase_unrecorded')
        elif io.db.execute("SELECT 1 FROM publication WHERE source=? AND room=? AND state='attempting' LIMIT 1", (row['event'],room)).fetchone():
            state = 'publication_unknown'
        elif pubs:
            state = 'publication_rejected'
        elif row['turn'] is None:
            state = 'native_handoff_unbound'
        elif row['native_phase'] is not None:
            state = 'native_ended_without_source_answer'
        else:
            state = 'awaiting_source_answer'
        holds = [dict(h) for h in io.db.execute('''SELECT h.item,h.reason,o.state AS outputState FROM reply_delivery_hold h
            JOIN output o ON o.item=h.item WHERE o.turn=? ORDER BY o.rowid DESC LIMIT 101''', (row['turn'],))]
        outcomes.append({'ordinal':row['ordinal'],'sourceEventId':row['event'],
            'roomId':room,'audience':source['audience'],'nativeTurn':row['turn'],
            'nativeEnd':row['native_phase'],'responseState':state,
            'publications':pubs[:100],'publicationsTruncated':len(pubs)>100,
            'heldFinals':holds[:100],'heldFinalsTruncated':len(holds)>100,'taskCompletion':'not_inferred'})
    return {'version':1,'agentId':io.binding['agent'],'nativeThread':io.binding['thread'],
            'roomId':room,'visibility':'owner-private','communicationIsNotTaskOwnership':True,
            'outcomes':outcomes,'nextAfter':outcomes[-1]['ordinal'] if len(rows)>limit and not recent else None,
            'olderBefore':outcomes[-1]['ordinal'] if len(rows)>limit and recent else None}
