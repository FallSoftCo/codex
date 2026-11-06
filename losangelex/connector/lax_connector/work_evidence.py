"""Persistent acceptance contracts and retained verification evidence.

The runtime proves artifact identity and native execution, not semantic truth.
The lead remains responsible for reviewing whether evidence meets human intent.
"""
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path


def wire(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(wire(value).encode()).hexdigest()
def key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',value):raise ValueError('Use a stable bounded evidence key')
    return value


class WorkEvidence:
    def __init__(self,ledger):
        self.ledger=ledger;self.db=ledger.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS acceptance_contract(work TEXT,revision INTEGER,body TEXT,digest TEXT,created REAL,PRIMARY KEY(work,revision));
          CREATE TABLE IF NOT EXISTS verification(work TEXT,key TEXT,contract TEXT,criterion TEXT,verdict TEXT,body TEXT,turn TEXT,created REAL,PRIMARY KEY(work,key));
          CREATE TABLE IF NOT EXISTS verification_material(work TEXT,material TEXT,PRIMARY KEY(work,material));
          CREATE TABLE IF NOT EXISTS evidence_blob(sha256 TEXT PRIMARY KEY,content BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS native_verification(turn TEXT,item TEXT,body TEXT,PRIMARY KEY(turn,item));
          CREATE TABLE IF NOT EXISTS completion_receipt(work TEXT PRIMARY KEY,contract TEXT,body TEXT,created REAL);
        ''')

    def native_command(self,turn,item):
        if item.get('type')!='commandExecution':return
        observation={k:item.get(k) for k in ('id','type','command','cwd','status','exitCode')}
        observation['commandDigest']=hashlib.sha256(str(observation['command']).encode()).hexdigest()
        observation['command']=str(observation['command'])[:4096]
        observation['reportedHashes']=sorted(set(re.findall(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])',str(item.get('aggregatedOutput','')))))[:64]
        observation['outputDigest']=hashlib.sha256(str(item.get('aggregatedOutput','')).encode()).hexdigest()
        with self.db:self.db.execute('INSERT INTO native_verification VALUES(?,?,?) ON CONFLICT DO NOTHING',(turn,item['id'],wire(observation)))

    def contract(self,work):
        row=self.db.execute('SELECT * FROM acceptance_contract WHERE work=? ORDER BY revision DESC LIMIT 1',(work,)).fetchone()
        return {**dict(row),'body':json.loads(row['body'])} if row else None

    def define(self,work,value,turn):
        record=self.ledger.work(work)
        if self.db.execute('SELECT 1 FROM completion_receipt WHERE work=?',(work,)).fetchone():raise ValueError('Completion evidence is sealed; reconcile its original publication')
        if not self.ledger.is_lead or record['state'] not in ('working','ready'):raise ValueError('Only active original lead work defines acceptance')
        if not self.db.execute('SELECT 1 FROM turn_work WHERE work=? AND turn=?',(work,turn)).fetchone():raise ValueError('Acceptance must belong to this admitted turn')
        if not isinstance(value,dict) or set(value)!={'subject','criteria','reason'}:raise ValueError('Acceptance requires subject, criteria and reason')
        if any(not isinstance(value[k],str) or not value[k].strip() or len(value[k].encode())>1024 for k in ('subject','reason')):raise ValueError('Identify the exact product revision and scope rationale')
        criteria=value['criteria']
        if not isinstance(criteria,list) or not 1<=len(criteria)<=32:raise ValueError('Use one to32 concrete acceptance criteria')
        for c in criteria:
            if not isinstance(c,dict) or set(c)!={'id','requirement'}:raise ValueError('Each criterion needs id and requirement')
            key(c['id'])
            if not isinstance(c['requirement'],str) or not c['requirement'].strip() or len(c['requirement'].encode())>1024:raise ValueError('Bounded testable requirement required')
        if len({c['id'] for c in criteria})!=len(criteria):raise ValueError('Duplicate criterion')
        body={**value,'originalSource':record['source'],'originalIntentDigest':digest(json.loads(record['human']))};prior=self.contract(work)
        if prior and prior['body']==body:return prior
        if prior:
            previous={c['id']:c['requirement'] for c in prior['body']['criteria']};new={c['id']:c['requirement'] for c in criteria}
            if any(new.get(k)!=v for k,v in previous.items()):raise ValueError('Existing requirements cannot be silently removed or weakened; preserve them and record a genuine blocker')
        revision=prior['revision']+1 if prior else 1
        with self.db:self.db.execute('INSERT INTO acceptance_contract VALUES(?,?,?,?,?)',(work,revision,wire(body),digest(body),time.time()))
        return self.contract(work)

    async def verify(self,work,value,turn,rpc,thread):
        contract=self.contract(work);record=self.ledger.work(work)
        if not self.ledger.is_lead or not contract:raise ValueError('Define acceptance criteria before verification')
        if not isinstance(value,dict) or set(value)!={'key','criterion','verdict','summary','artifacts','native'}:raise ValueError('Verification requires key, criterion, verdict, summary, artifacts and native command identity')
        key(value['key']);key(value['criterion'])
        if value['criterion'] not in {c['id'] for c in contract['body']['criteria']}:raise ValueError('Unknown acceptance criterion')
        if value['verdict'] not in ('pass','fail','blocked'):raise ValueError('Explicit pass, fail or blocked required')
        if not isinstance(value['summary'],str) or not value['summary'].strip() or len(value['summary'].encode())>2048:raise ValueError('Record what was actually verified and its limits')
        prior=self.db.execute('SELECT * FROM verification WHERE work=? AND key=?',(work,value['key'])).fetchone()
        request={**value,'contract':contract['digest']}
        if prior:
            if json.loads(prior['body'])['request']!=request:raise ValueError('Original verification key cannot change')
            return json.loads(prior['body'])
        if self.db.execute('SELECT 1 FROM completion_receipt WHERE work=?',(work,)).fetchone():raise ValueError('Completion evidence is sealed')
        if record['state'] not in ('ready','working') or not self.db.execute('SELECT 1 FROM turn_work WHERE work=? AND turn=?',(work,turn)).fetchone():raise ValueError('Verification requires current admitted work')
        artifacts=value['artifacts'];native=value['native'];blobs=[];receipts=[]
        if not isinstance(artifacts,list) or not 1<=len(artifacts)<=4:raise ValueError('Retain one to four bounded evidence files, not ephemeral references')
        for a in artifacts:
            if not isinstance(a,dict) or set(a)!={'path','sha256'} or not isinstance(a['path'],str) or not Path(a['path']).is_absolute() or not isinstance(a['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',a['sha256']):raise ValueError('Use an absolute evidence file and expected SHA256')
            fd=os.open(a['path'],os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            try:
                st=os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=262144:raise ValueError('Evidence must be a nonempty regular file at most256KiB; retain a focused receipt for larger outputs')
                with os.fdopen(os.dup(fd),'rb') as f:content=f.read(262145)
                if len(content)>262144 or hashlib.sha256(content).hexdigest()!=a['sha256']:raise ValueError('Evidence content does not match the supplied digest')
            finally:os.close(fd)
            blobs.append((a['sha256'],content));receipts.append({**a,'bytes':len(content)})
        if not isinstance(native,dict) or set(native)!={'turnId','itemId'} or any(not isinstance(v,str) or not v for v in native.values()):raise ValueError('Reference an actual native verification command in this lead context')
        execution=self.db.execute('SELECT body FROM native_verification WHERE turn=? AND item=?',(native['turnId'],native['itemId'])).fetchone()
        if not execution:raise ValueError('No retained native command receipt; inspect lead_work recentCommands and run an actual verification command')
        observation=json.loads(execution['body'])
        if any(a['sha256'] not in observation.get('reportedHashes',[]) for a in receipts):raise ValueError('The native verification command must print each retained artifact SHA256; unrelated command success is not evidence')
        if observation['status']!='completed' or observation['exitCode']!=0:raise ValueError('Verification requires an actually successful native command')
        if not self.db.execute('SELECT 1 FROM turn_work WHERE work=? AND turn=?',(work,native['turnId'])).fetchone():raise ValueError('Native evidence belongs to other work')
        proof={'request':request,'artifacts':receipts,'native':{'threadId':thread,'turnId':native['turnId'],'item':observation,'outputDigest':observation['outputDigest']},'recordedAt':time.time(),'semanticReviewer':self.ledger.agent}
        with self.db:
            if self.contract(work)['digest']!=contract['digest']:raise ValueError('Acceptance changed during verification')
            for sha,content in blobs:self.db.execute('INSERT INTO evidence_blob VALUES(?,?) ON CONFLICT DO NOTHING',(sha,content))
            self.db.execute('INSERT INTO verification VALUES(?,?,?,?,?,?,?,?)',(work,value['key'],contract['digest'],value['criterion'],value['verdict'],wire(proof),turn,time.time()))
            material=digest([contract['digest'],value['criterion'],value['verdict'],sorted(a['sha256'] for a in receipts)])
            changed=self.db.execute('INSERT INTO verification_material VALUES(?,?) ON CONFLICT DO NOTHING',(work,material)).rowcount
            if changed:self.db.execute('UPDATE work SET progress_revision=progress_revision+1,no_progress=0 WHERE id=?',(work,))
        return proof

    def completion(self,work):
        contract=self.contract(work)
        if not contract:raise ValueError('Completion requires a persistent acceptance contract and verified evidence for every criterion')
        pending=self.ledger.dependencies(work)
        # Previously delivered needs-input prose is historical, not an unresolved callback.
        if any(pending[k] for k in ('assignments','questions','admitting')):raise ValueError('Outstanding work or uncertain communication prevents completion')
        rows=self.db.execute('SELECT * FROM verification WHERE work=? AND contract=? ORDER BY rowid',(work,contract['digest'])).fetchall();latest={r['criterion']:r for r in rows};proofs=[]
        for c in contract['body']['criteria']:
            r=latest.get(c['id'])
            if not r or r['verdict']!='pass':raise ValueError('Unverified acceptance criterion: '+c['id'])
            proof=json.loads(r['body'])
            for a in proof['artifacts']:
                b=self.db.execute('SELECT content FROM evidence_blob WHERE sha256=?',(a['sha256'],)).fetchone()
                if not b or hashlib.sha256(b[0]).hexdigest()!=a['sha256']:raise ValueError('Retained evidence missing or corrupt')
            proofs.append({'criterion':c['id'],'verificationKey':r['key'],'receiptDigest':digest(proof)})
        return {'workId':work,'sourceEventId':self.ledger.work(work)['source'],'contractDigest':contract['digest'],'subject':contract['body']['subject'],'criteria':proofs}

    def seal(self,work):
        receipt=self.completion(work);old=self.db.execute('SELECT body FROM completion_receipt WHERE work=?',(work,)).fetchone()
        if old and old['body']!=wire(receipt):raise ValueError('Original completion receipt changed')
        self.db.execute('INSERT INTO completion_receipt VALUES(?,?,?,?) ON CONFLICT DO NOTHING',(work,receipt['contractDigest'],wire(receipt),time.time()))
        return receipt

    def snapshot(self,work):
        contract=self.contract(work);rows=self.db.execute('SELECT key,criterion,verdict,created FROM verification WHERE work=? ORDER BY rowid DESC LIMIT 32',(work,)).fetchall()
        complete=self.db.execute('SELECT body FROM completion_receipt WHERE work=?',(work,)).fetchone()
        commands=self.db.execute('SELECT n.turn,n.item,n.body FROM native_verification n JOIN turn_work t ON n.turn=t.turn WHERE t.work=? ORDER BY n.rowid DESC LIMIT 5',(work,)).fetchall()
        return {'recentCommands':[{'turnId':r['turn'],'itemId':r['item'],**json.loads(r['body'])} for r in commands],'contract':contract,'verifications':[dict(r) for r in rows],'completion':json.loads(complete[0]) if complete else None}
