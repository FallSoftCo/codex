"""Read your original per-source response outcomes. No migration/retry/model.

Owner-private inspection only: the output can include private source identifiers.
Never publish the complete report to a room. Accepted answers are communication
receipts, not assertions that the associated business work is complete.
"""
import argparse
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID
from .runtime_files import private_file
from .room_reply_state import report


def inspect(config_path, room, *, after=0, limit=100):
    private_file(config_path)
    config = json.loads(Path(config_path).read_text())
    path = Path(config['state']) / 'conversation-io.sqlite'
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError('Exact original private state path required')
    private_file(path)
    db = sqlite3.connect('file:' + quote(str(path), safe='/:') + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    binding = {'authority':str(UUID(config['authorityId'])), 'agent':str(UUID(config['agentId'])),
               'thread':config['nativeThreadId']}
    try:
        if json.loads(db.execute('SELECT value FROM binding WHERE id=1').fetchone()[0]) != binding:
            raise ValueError('Original native owner binding differs')
        # One consistent read transaction; never creates/migrates a live journal.
        db.execute('BEGIN')
        return report(SimpleNamespace(db=db,binding=binding), str(UUID(room)), after=after, limit=limit)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--room', required=True)
    parser.add_argument('--after', type=int, default=0)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(inspect(args.config,args.room,after=args.after,limit=args.limit)))


if __name__ == '__main__':
    main()
