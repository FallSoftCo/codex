"""Event-driven native final delivery through the original publication ledger."""
import asyncio
import hashlib
import json
import random
from .errors import HttpFailure


class RoomOutput:
    def __init__(self, io, tools):
        self.io, self.tools = io, tools
        self.wake = asyncio.Event()
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())
        self.wake.set()

    async def deliver(self, row):
        source = self.io.source(row['turn'])
        if not source:
            # A native turn may contain inputs from different rooms/audiences.
            # No guess or automatic audience widening is allowed.
            return False
        if (source['data']['authorKind'] != 'human' and source.get('kind') != 'request'
                and not source['data'].get('expectsReply')):
            # Addressed peer answers must remain deliberate model publications.
            # Automatically answering an automatic peer answer causes wake loops.
            self.io.finish(row['item'], 'suppressed', 'Peer publication remains explicit')
            return True
        key = hashlib.sha256(('native-final\0'+row['item']).encode()).hexdigest()
        async with self.tools.publish_lock:
            publications = self.io.publications(row['turn'], source['id'])
            for prior in publications:
                if prior['key'] == key:
                    continue
                if prior['state'] == 'attempting':
                    path = self.tools.state/(prior['key']+'.json')
                    ledger = json.loads(path.read_text())
                    payload = ledger['payload']
                    args = {k: v for k, v in payload.items() if k in {
                        'body','audience','recipientId','sourceEventId','responsePhase'}}
                    # publish sees the original sending ledger and performs GET
                    # of the same command only; uncertain writes are not replayed.
                    await self.tools.publish(prior['room'], args, prior['key'], turn=row['turn'])
                    prior['state'] = 'accepted'
                if prior['state'] == 'accepted':
                    self.io.finish(row['item'], 'suppressed', 'Explicit final already accepted')
                    return True
            chunks=[]
            rest=row['body']
            while rest:
                encoded=rest.encode()
                if len(encoded)<=6000:
                    chunks.append(rest);break
                piece=encoded[:6000].decode('utf-8',errors='ignore')
                chunks.append(piece);rest=rest[len(piece):]
            for index,body in enumerate(chunks):
                args = {'body': body, 'audience': source['audience'],
                        'responsePhase': row['phase'] if index==len(chunks)-1 else 'update',
                        'sourceEventId': source['id']}
                if source['audience'] == 'direct':
                    args['recipientId'] = source['author']
                part_key=key if index==len(chunks)-1 else key+'-'+str(index)
                await self.tools.publish(source['room'], args, part_key, turn=row['turn'])
            self.io.finish(row['item'], 'accepted')
            return True

    async def run(self):
        attempts = 0
        while True:
            await self.wake.wait()
            self.wake.clear()
            retry = False
            for row in self.io.pending():
                try:
                    await self.deliver(row)
                except asyncio.CancelledError:
                    raise
                except HttpFailure as error:
                    if error.status in (400,403,409):
                        self.io.finish(row['item'],'blocked',str(error))
                    else:retry=True
                except Exception:
                    # Cheap transport reconciliation only, never model sampling
                    # or a replacement native input. The original output persists.
                    retry = True
            if retry:
                attempts += 1
                await asyncio.sleep(min(300, 2**min(attempts, 8))*random.uniform(.8,1.2))
                self.wake.set()
            else:
                attempts = 0

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
