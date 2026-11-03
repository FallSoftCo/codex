"""Passive own-author canonical final receipts, not native input or command ACKs.

The authenticated room stream is also authoritative for replies sent outside a
native tool callback. Store structured provenance without bodies. A canonical
reply does not clear an uncertain local command or imply business completion.
"""
import hashlib
import json
from uuid import UUID


SCHEMA = '''
CREATE TABLE IF NOT EXISTS canonical_reply(
 event TEXT PRIMARY KEY,source TEXT NOT NULL,room TEXT NOT NULL,proof TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS canonical_reply_source ON canonical_reply(source,room);
CREATE TABLE IF NOT EXISTS reply_publication_event(
 turn TEXT NOT NULL,key TEXT NOT NULL,event TEXT NOT NULL,PRIMARY KEY(turn,key));
CREATE INDEX IF NOT EXISTS reply_publication_event_id ON reply_publication_event(event);
'''


def observe(io, event):
    """Only call with an authenticated canonical feed/validated HTTP receipt.

    No inferred turn is needed. Receipts can arrive before their original input
    binds; exact original source/audience checks happen when projecting outcomes.
    """
    data = event.get('data', {})
    identity = event.get('id')
    old = io.db.execute('SELECT proof FROM canonical_reply WHERE event=?', (identity,)).fetchone()
    own_final = (event.get('authority') == io.binding['authority']
                 and event.get('author') == io.binding['agent']
                 and data.get('authorKind') == 'agent' and event.get('kind') == 'message'
                 and data.get('responsePhase') in ('answer', 'blocked') and event.get('source'))
    if not own_final and not old:
        return False
    if not own_final:
        raise ValueError('Original canonical own reply identity changed')
    for field in ('id', 'authority', 'room', 'author', 'source'):
        if str(UUID(event[field])) != event[field]:
            raise ValueError('Canonical own reply UUID required')
    audience, recipient = event.get('audience'), event.get('recipient')
    if audience not in ('room', 'direct') or audience == 'direct' and not recipient:
        raise ValueError('Canonical own reply audience required')
    if recipient is not None and str(UUID(recipient)) != recipient:
        raise ValueError('Canonical reply counterpart required')
    if type(event.get('seq')) is not int or event['seq'] < 1 or not isinstance(event.get('body'), str):
        raise ValueError('Canonical reply sequence/body required')
    proof = {k: event[k] for k in ('id', 'authority', 'room', 'author', 'source', 'kind', 'seq', 'audience')}
    proof.update(recipient=recipient, phase=data['responsePhase'],
                 bodySha256=hashlib.sha256(event['body'].encode()).hexdigest())
    encoded = json.dumps(proof, sort_keys=True)
    if old and old['proof'] != encoded:
        raise ValueError('Original canonical own reply contents changed')
    with io.db:
        io.db.execute('INSERT INTO canonical_reply VALUES(?,?,?,?) ON CONFLICT DO NOTHING',
                      (identity, event['source'], event['room'], encoded))
    return True


def visible_to_source(io, source, proof):
    if proof['source'] != source['id'] or proof['room'] != source['room']:
        return False
    if source['audience'] == 'direct':
        return (source.get('recipient') == io.binding['agent'] and proof['audience'] == 'direct'
                and proof['recipient'] == source['author'])
    return proof['audience'] == 'room' or proof['recipient'] == source['author']


def local_visibility(io, source, turn, key):
    """None means legacy scope unrecorded, not new canonical acceptance."""
    if not io.db.execute("SELECT 1 FROM sqlite_master WHERE name='reply_publication_event' AND type='table'").fetchone():
        return None
    row = io.db.execute('''SELECT c.proof FROM reply_publication_event p
        LEFT JOIN canonical_reply c ON c.event=p.event WHERE p.turn=? AND p.key=?''', (turn,key)).fetchone()
    if row is None:
        return None
    return visible_to_source(io, source, json.loads(row['proof'])) if row['proof'] else False


def _scope(io, source, prefix=''):
    proof = prefix+'proof'
    base = prefix+'source=? AND '+prefix+'room=?'
    args = [source['id'],source['room']]
    if source['audience'] == 'direct':
        return (base+f" AND json_extract({proof},'$.audience')='direct' AND json_extract({proof},'$.recipient')=? AND ?=?",
                args+[source['author'],source.get('recipient'),io.binding['agent']])
    return (base+f" AND (json_extract({proof},'$.audience')='room' OR json_extract({proof},'$.recipient')=?)",
            args+[source['author']])


def accepted_local_phases(io, source):
    query = '''SELECT DISTINCT d.phase FROM publication p
        LEFT JOIN reply_publication_phase d ON d.turn=p.turn AND d.key=p.key'''
    args = [source['id'],source['room']]
    present = io.db.execute("SELECT 1 FROM sqlite_master WHERE name='canonical_reply' AND type='table'").fetchone()
    if present:
        query += ''' LEFT JOIN reply_publication_event e ON e.turn=p.turn AND e.key=p.key
            LEFT JOIN canonical_reply c ON c.event=e.event'''
    query += " WHERE p.source=? AND p.room=? AND p.state='accepted'"
    if present:
        scope, scope_args = _scope(io,source,'c.')
        query += ' AND (e.event IS NULL OR ('+scope+'))'
        args += scope_args
    return [dict(r) for r in io.db.execute(query,args)]


def receipts(io, source, *, exclude_key=None):
    """Owner-private exact source/counterpart projection, also on old read-only DBs."""
    if not io.db.execute("SELECT 1 FROM sqlite_master WHERE name='canonical_reply' AND type='table'").fetchone():
        return []
    scope, args = _scope(io, source)
    rows = io.db.execute('SELECT proof FROM canonical_reply WHERE '+scope+' ORDER BY rowid DESC LIMIT 101', args).fetchall()
    result = []
    for row in rows:
        proof = json.loads(row['proof'])
        if not visible_to_source(io, source, proof):
            continue
        links = [dict(r) for r in io.db.execute('SELECT turn,key FROM reply_publication_event WHERE event=? LIMIT 101', (proof['id'],))]
        if exclude_key and any(r['key'] == exclude_key for r in links):
            continue  # original automatic-final acceptance is reconciled normally
        result.append({'eventId': proof['id'], 'phase': proof['phase'], 'seq': proof['seq'],
                       'audience': proof['audience'], 'recipientId': proof['recipient'],
                       'bodySha256': proof['bodySha256'], 'localPublications': links[:100],
                       'localPublicationsTruncated': len(links)>100})
    return result
