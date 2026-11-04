"""Two-second answer readiness and finite native review, separate from task work.

The server condition is a communication compare-and-append, never a speaker
reservation. Review is application feedback in the SAME native context, not a
human message, peer assignment, periodic wake or a new model/daemon.
"""
import asyncio
import hashlib
import json
import time


class ReplyContextChanged(Exception):
    def __init__(self, snapshot):
        super().__init__('A peer replied; reconsider the unpublished answer')
        self.snapshot = snapshot


class ReplyWindow:
    def __init__(self, io, rpc, *, idle=lambda: True, on_review=None):
        self.io, self.rpc, self.idle, self.on_review = io, rpc, idle, on_review
        self.binding_ready = asyncio.Event()
        self.binding_ready.set()
        self.db = io.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS reply_ready(
                key TEXT PRIMARY KEY, source TEXT NOT NULL, ready REAL NOT NULL,
                observed INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS reply_seen(
                turn TEXT NOT NULL, source TEXT NOT NULL, observed INTEGER NOT NULL,
                PRIMARY KEY(turn,source));
            CREATE TABLE IF NOT EXISTS reply_review(
                item TEXT PRIMARY KEY, source TEXT NOT NULL, canonical TEXT NOT NULL,
                snapshot TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                turn TEXT, acknowledgement TEXT);
            CREATE INDEX IF NOT EXISTS reply_review_turn ON reply_review(turn);
        ''')

    def source(self, turn):
        row = self.db.execute('SELECT canonical FROM reply_review WHERE turn=? ORDER BY rowid DESC LIMIT 1',
                              (turn,)).fetchone()
        return json.loads(row['canonical']) if row else None

    def private_final(self, turn, source):
        reviewed = self.source(turn)
        return reviewed is not None and reviewed['id'] == source['id']

    def seen(self, turn, snapshot):
        if not turn:
            return
        with self.db:
            self.db.execute('''INSERT INTO reply_seen VALUES(?,?,?) ON CONFLICT(turn,source)
                DO UPDATE SET observed=max(observed,excluded.observed)''',
                (turn,snapshot['sourceEventId'],snapshot['observedThrough']))

    async def condition(self, key, source, turn):
        if (source.get('data',{}).get('authorKind') != 'human'
                or source['audience'] != 'room' or source.get('recipient')):
            return None
        await self.binding_ready.wait()
        seen = self.db.execute('SELECT observed FROM reply_seen WHERE turn=? AND source=?',
                               (turn,source['id'])).fetchone()
        observed = seen['observed'] if seen else source['seq']
        with self.db:
            self.db.execute('INSERT INTO reply_ready VALUES(?,?,?,?) ON CONFLICT(key) DO NOTHING',
                            (key,source['id'],time.time(),observed))
        row = self.db.execute('SELECT * FROM reply_ready WHERE key=?',(key,)).fetchone()
        if row['source'] != source['id']:
            raise ValueError('Answer readiness belongs to another original source')
        # Only the readiness deadline is timed; there is no polling/model work.
        await asyncio.sleep(max(0,min(2,row['ready']+2-time.time())))
        return {'observedThrough':row['observed']}

    async def review(self, row, source, snapshot):
        prior = self.db.execute('SELECT * FROM reply_review WHERE item=?',(row['item'],)).fetchone()
        if prior:
            if prior['acknowledgement'] is not None:
                return True
            # A lost native acknowledgement is NOT absence of execution.
            # Retain original payload for explicit reconciliation, never re-send.
            from .errors import HttpFailure
            raise HttpFailure(409,'Original reply review acknowledgement needs reconciliation',
                              code='REPLY_REVIEW_UNCONFIRMED',may_apply=True)
        if not self.idle():
            return False  # Current useful work wins; turn completion wakes output.
        instruction = (
            'This is application feedback on your unpublished answer, not a new human request. '
            'Another room member responded during/before your readiness window. Compare your '
            'draft against the actual peer replies. If it adds no useful information, finish '
            'silently WITHOUT publishing. If you have a material correction, new fact, necessary '
            'question or useful additional result, use hollywood_publish explicitly with the '
            'original room/source/audience and only that addition. Your normal final for this '
            'review stays private. Do not restate the peer answer, create assignments, continue '
            'business work, poll or send acknowledgements merely to complete this review. '
            'Read full original peer messages with hollywood_read_room if previews are clipped.')
        feedback = {'kind':'application','instruction':instruction,
                    'originalSource':{'id':source['id'],'roomId':source['room'],'audience':source['audience']},
                    'unpublishedDraftPreview':row['body'].encode()[:2400].decode('utf-8','ignore'),
                    'draftTruncated':len(row['body'].encode())>2400,'peerContext':json.loads(json.dumps(snapshot))}
        encoded = json.dumps(feedback,ensure_ascii=False)
        while len(encoded.encode()) > 9000:
            feedback['unpublishedDraftPreview']=feedback['unpublishedDraftPreview'].encode()[:len(feedback['unpublishedDraftPreview'].encode())//2].decode('utf-8','ignore')
            feedback['draftTruncated']=True
            for peer in feedback['peerContext']['peerReplies']:
                peer['bodyPreview']=peer['bodyPreview'].encode()[:max(0,len(peer['bodyPreview'].encode())//2)].decode('utf-8','ignore')
                peer['truncated']=True
            encoded=json.dumps(feedback,ensure_ascii=False)
        identity = hashlib.sha256(row['item'].encode()).hexdigest()
        payload = {'threadId':self.io.binding['thread'],'input':[],
                   'turnTrigger':'hollywood.reply_review:'+identity,
                   'parentTurnId':row['turn'],
                   'toolOutput':{'name':'hollywood_reply_review','output':encoded,'retain':True}}
        with self.db:
            self.db.execute('INSERT INTO reply_review VALUES(?,?,?,?,?,?,?,?)',
                (row['item'],source['id'],json.dumps(source,sort_keys=True),json.dumps(snapshot,sort_keys=True),
                 json.dumps(payload,sort_keys=True),'handoff',None,None))
        self.binding_ready.clear()
        try:
            receipt = await self.rpc.call('turn/start',payload)
            turn = receipt['turn']['id']
            with self.db:
                self.db.execute("UPDATE reply_review SET state='acknowledged',turn=?,acknowledgement=? WHERE item=?",
                                (turn,json.dumps(receipt,sort_keys=True),row['item']))
            self.seen(turn,snapshot)
            if self.on_review:
                self.on_review(turn,source)
            return True
        finally:
            self.binding_ready.set()
