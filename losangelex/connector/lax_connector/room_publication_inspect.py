"""Inspect one original publication without resending it or reopening a final.

Run as the original connector account. This reads bounded private receipts and
a read-only SQLite transaction; it never constructs/migrates ConversationIO,
starts a model, contacts an endpoint, or changes an output/publication state.
Only identifiers, hashes and allowlisted status metadata leave this inspector.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import UUID, uuid5

from .runtime_files import private_file


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, limit):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError('Use the exact original private file, not an alias')
    private_file(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Original metadata exceeded inspection bound')
    return raw


def inspect_original(config_file, key, turn):
    if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('Exact original publication key required')
    if not isinstance(turn, str) or not 1 <= len(turn) <= 256:
        raise ValueError('Exact original native turn required')
    config = json.loads(_read(config_file, 1024 * 1024))
    binding = {'authority': str(UUID(config['authorityId'])),
               'agent': str(UUID(config['agentId'])), 'thread': config['nativeThreadId']}
    state = Path(config['state'])
    if not state.is_absolute() or state.resolve(strict=True) != state:
        raise ValueError('Exact original connector state required')
    path = state / 'publications' / (key + '.json')
    raw = _read(path, 128 * 1024)
    record = json.loads(raw)
    room, payload = str(UUID(record['room'])), record['payload']
    fingerprint = _hash(json.dumps({'room': room, 'payload': payload}, sort_keys=True).encode())
    if (record['fingerprint'] != fingerprint
            or payload['operationId'] != 'native-room:' + str(uuid5(UUID(binding['agent']), key))
            or payload.get('kind') != 'message'
            or record['state'] not in {'sending', 'rejected', 'accepted'}):
        raise ValueError('Original publication binding or fingerprint differs')
    body = payload['body']
    if not isinstance(body, str) or not 1 <= len(body.encode()) <= 6000:
        raise ValueError('Original message body is malformed')
    for field in ('sourceEventId', 'recipientId'):
        if payload.get(field) is not None:
            UUID(payload[field])
    if payload.get('audience') not in {'room', 'direct'}:
        raise ValueError('Original message audience differs')
    if payload['audience'] == 'direct' and not payload.get('recipientId'):
        raise ValueError('Original private recipient is missing')
    phase = payload.get('responsePhase')
    if phase not in {None, 'answer', 'blocked', 'update', 'message'}:
        raise ValueError('Original message phase differs')
    database = state / 'conversation-io.sqlite'
    # Do not instantiate ConversationIO: its constructor creates/migrates state.
    private_file(database)
    if database.resolve(strict=True) != database:
        raise ValueError('Original conversation database is aliased')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        actual = db.execute('SELECT value FROM binding WHERE id=1').fetchone()
        if not actual or json.loads(actual[0]) != binding:
            raise ValueError('Original conversation owner/thread differs')
        rows = db.execute('SELECT source,room,state FROM publication WHERE turn=? AND key=?',
                          (turn, key)).fetchall()
        if len(rows) != 1 or rows[0] != (payload.get('sourceEventId'), room, record['state']):
            raise ValueError('Original native publication row is missing or differs')
        ended = db.execute('SELECT phase FROM native_end WHERE turn=?', (turn,)).fetchone()
        source = db.execute('SELECT event,room FROM input_source WHERE event=? AND turn=?',
                            (payload.get('sourceEventId'), turn)).fetchone()
    if source != (payload.get('sourceEventId'), room):
        raise ValueError('Original causal input/turn/room differs')
    # A concurrent atomic outbox replacement is not a coherent snapshot.
    if _read(path, 128 * 1024) != raw:
        raise ValueError('Publication changed during inspection; retain uncertainty')
    error = record.get('error', {})
    code = error.get('code')
    if not isinstance(code, str) or not re.fullmatch('[A-Z][A-Z0-9_]{0,79}', code):
        code = None
    status = error.get('status')
    return {'schema': 'lax-original-publication-inspection/v1',
            'authorityId': binding['authority'], 'agentId': binding['agent'],
            'nativeThreadId': binding['thread'], 'nativeTurnId': turn,
            'nativePhase': ended[0] if ended and ended[0] in {'completed', 'failed', 'interrupted'} else 'unconfirmed',
            'key': key, 'operationId': payload['operationId'], 'roomId': room,
            'sourceEventId': payload.get('sourceEventId'), 'recipientId': payload.get('recipientId'),
            'audience': payload['audience'], 'responsePhase': phase,
            'localState': record['state'], 'fingerprint': fingerprint,
            'bodyBytes': len(body.encode()), 'bodySha256': _hash(body.encode()),
            'originalReceiptSha256': _hash(raw),
            'httpStatus': status if type(status) is int and 100 <= status <= 599 else None,
            'errorCode': code,
            'canonicalOutcome': 'not-read; local rejection/acceptance is not a new canonical read',
            'mutationDispatched': False, 'originalNativeTurnReplayed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--turn', required=True)
    args = parser.parse_args()
    print(json.dumps(inspect_original(args.config, args.key, args.turn), sort_keys=True))


if __name__ == '__main__':
    main()
