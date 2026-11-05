"""Event-driven native final delivery through the original publication ledger."""
import asyncio
import hashlib
import json
import logging
import random
from .errors import HttpFailure
from .conversation_io import reply_expected


class RoomOutput:
    def __init__(self, io, tools):
        self.io, self.tools = io, tools
        self.wake = asyncio.Event()
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())
        self.wake.set()

    async def deliver(self, row):
        from .room_reply_window import ReplyContextChanged
        try:
            return await self._deliver(row)
        except ReplyContextChanged as error:
            if not self.tools.reply_window:
                raise
            source=self.io.source(row['turn'])
            if await self.tools.reply_window.review(row,source,error.snapshot):
                self.io.finish(row['item'],'suppressed','Unpublished draft submitted for peer-response review')
                return True
            return False

    async def _deliver(self, row):
        if self.io.is_output_held(row['item']):
            return False  # A source-policy change never re-admits a retained final.
        source = self.io.source(row['turn'])
        if self.tools.project:
            return await self.tools.project.native_final(row,source)
        if not source:
            # A native turn may contain inputs from different rooms/audiences.
            # No guess or automatic audience widening is allowed.
            self.io.hold_ambiguous_final(row)
            return False
        if not reply_expected(source):
            # Addressed peer answers must remain deliberate model publications.
            # Automatically answering an automatic peer answer causes wake loops.
            self.io.finish(row['item'], 'suppressed', 'Peer publication remains explicit')
            return True
        window=getattr(self.tools,'reply_window',None)
        if window and window.private_final(row['turn'],source):
            self.io.finish(row['item'],'suppressed','Reply review final is private; additions are deliberate publications')
            return True
        key = hashlib.sha256(('native-final\0'+row['item']).encode()).hexdigest()
        async with self.tools.publish_lock:
            from .room_reply_receipts import receipts, local_visibility
            if receipts(self.io, source, exclude_key=key):
                self.io.finish(row['item'], 'suppressed', 'Source-addressed canonical final already accepted')
                return True
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
                if prior['state'] == 'accepted' and local_visibility(self.io,source,row['turn'],prior['key']) is not False:
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
                await self.tools.publish(source['room'], args, part_key, turn=row['turn'], coordinate=index==0 and row['phase']=='answer')
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
                except Exception as error:
                    # Cheap transport reconciliation only, never model sampling
                    # or a replacement native input. The original output persists.
                    logging.getLogger(__name__).exception('Original room output deferred: %s',row['item'])
                    with self.io.db:
                        self.io.db.execute("UPDATE output SET reason=? WHERE item=? AND state='queued'",
                            ('Deferred publication: '+type(error).__name__+': '+str(error)[:240],row['item']))
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
