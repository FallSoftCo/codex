"""Queue one verified completed reply after passive-source misclassification.

Run as the original connector UID while that connector is stopped. This command
uses its existing process lock, preserves native item/source IDs and starts no
model, native transport, publisher or service. Normal outbox startup delivers it.
"""
import argparse
import json
import os
import stat
from pathlib import Path
from .runtime_files import private_file, exclusive_lock
from .conversation_io import ConversationIO


def recover(config_file, item, source_event):
    private_file(config_file)
    config = json.loads(Path(config_file).read_text())
    state = Path(config['state'])
    if not state.is_absolute():
        raise ValueError('Original absolute connector state required')
    if os.name == 'nt':
        from .windows_ipc import private_path
        private_path(state, directory=True)
    else:
        info = state.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError('Original private connector state owner required')
    lock = state / 'connector.lock'
    private_file(lock)
    with lock.open('r+') as owned:
        exclusive_lock(owned)  # Refuse a concurrent old or new connector owner.
        private_file(state / 'conversation-io.sqlite')
        io = ConversationIO(state / 'conversation-io.sqlite', authority=config['authorityId'],
                            agent=config['agentId'], thread=config['nativeThreadId'])
        try:
            return io.recover_passive_suppression(item, source_event)
        finally:
            io.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--item', required=True)
    parser.add_argument('--source-event', required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.config, args.item, args.source_event)))


if __name__ == '__main__':
    main()
