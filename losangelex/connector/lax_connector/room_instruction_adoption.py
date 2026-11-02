"""One CAS-bound instruction adoption and bounded ACK/acceptance reconciliation.

Called only while the existing connector process lock is held. Unknown native
dispatch stays held. A saved original native ACK can finish acceptance without
resending, and a later loaded reconnect reuses that exact accepted policy.
"""
import json
import os
from pathlib import Path
import re
import stat

from .room_participation import instructions_digest, loaded
from .runtime_files import private_file, state_directory
from .journal import saved


def private_directory(path):
    state_directory(path, parents=True, exist_ok=True)
    if os.name != 'nt':
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or path.resolve(strict=True) != path):
            raise PermissionError('Original private adoption directory required')


def read(path):
    private_file(path)
    with path.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Instruction receipt exceeded its metadata bound')
    return json.loads(raw)


def exclusive(path, value):
    # The existing connector process lock fences cooperating writers. Reuse the
    # platform's atomic/durable receipt writer; never replace an existing ACK.
    if path.exists():
        raise FileExistsError(str(path))
    saved(path, value)
    private_file(path)


class InstructionAdoption:
    def __init__(self, config, rpc, overrides):
        self.config, self.rpc, self.overrides = config, rpc, overrides
        identity = config.get('conversationInstructionAdoptionId')
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{64}', identity):
            raise ValueError('Instruction adoption requires the CAS-bound original release identity')
        if not rpc.shared:
            raise ValueError('Participation adoption requires the original shared native owner boundary')
        native = self.native_binding()
        self.binding = {'schema': 'lax-room-instruction-adoption/v1', 'adoptionId': identity,
            'authorityId': config['authorityId'], 'hostId': config['hostId'], 'agentId': config['agentId'],
            'nativeThreadId': config['nativeThreadId'], 'policy': config['conversationParticipationPolicy'],
            'instructionsSha256': instructions_digest(overrides), 'nativeBinding': native}
        self.root = Path(config['state'])
        private_directory(self.root)
        for part in ('instruction-adoptions', identity, instructions_digest(native)):
            self.root = self.root / part
            private_directory(self.root)
        self.intent, self.accepted = self.root / 'intent.json', self.root / 'accepted.json'
        self.mode = None

    def native_binding(self):
        path = Path(self.config['nativeServer']['manifest'])
        info = self.rpc.socket_path.stat()
        return {'manifestSha256': instructions_digest(self.rpc.manifest),
                'socketIdentity': [info.st_dev, info.st_ino, info.st_ctime_ns],
                'manifestPath': str(path)}

    def finish(self, receipt):
        if read(self.intent) != self.binding:
            raise ValueError('Original instruction adoption intent changed')
        if (receipt.get('threadId') != self.binding['nativeThreadId']
                or receipt.get('instructionAdoption') != self.binding
                or receipt.get('instructionAdoptionColdBoundary') is not True
                or receipt.get('instructionOverridesSha256') != instructions_digest(self.overrides)
                or receipt.get('resumed') is not True):
            raise ValueError('Original native instruction ACK is absent or mismatched')
        value = {'binding': self.binding, 'nativeResumeReceipt': receipt,
                 'nativeResumeReceiptSha256': instructions_digest(receipt)}
        if self.accepted.exists():
            if read(self.accepted) != value:
                raise ValueError('Original instruction acceptance differs')
        else:
            exclusive(self.accepted, value)

    async def begin(self):
        accepted = None
        if self.accepted.exists():
            accepted = read(self.accepted)
            if (accepted.get('binding') != self.binding
                    or instructions_digest(accepted['nativeResumeReceipt']) != accepted['nativeResumeReceiptSha256']):
                raise ValueError('Accepted instruction scope/native incarnation differs')
            self.finish(accepted['nativeResumeReceipt'])
        elif self.intent.exists():
            # Finish ONLY an original supported native ACK captured before the
            # acceptance write. Loaded status alone is never such evidence.
            receipt = Path(self.config['state']) / 'conversation-resume.json'
            if not receipt.exists():
                raise ValueError('Original instruction resume is uncertain; no resend or replacement adoption')
            self.finish(read(receipt))
            accepted = read(self.accepted)
        is_loaded = await loaded(self.rpc, self.binding['nativeThreadId'])
        if accepted:
            self.mode = 'accepted-loaded' if is_loaded else 'accepted-cold-resume'
            return {} if is_loaded else self.overrides
        if is_loaded:
            raise ValueError('Instruction adoption requires the original idle released native thread')
        exclusive(self.intent, self.binding)
        self.mode = 'first-cold-resume'
        return self.overrides

    def receipt_fields(self):
        return {'instructionAdoption': self.binding, 'instructionAdoptionState': self.mode,
                'instructionAdoptionColdBoundary': self.mode != 'accepted-loaded'}

    def complete(self, receipt):
        if self.native_binding() != self.binding['nativeBinding']:
            raise ValueError('Native incarnation changed during instruction adoption')
        if self.mode == 'first-cold-resume':
            self.finish(receipt)
