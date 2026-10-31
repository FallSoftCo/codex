"""Communication administration with original native-call/HTTP step receipts.

Uses the existing domain workflows. It does not fabricate participation or expose
host provisioning as a room permission. Unknown writes are inspected, never sent
again; completed read snapshots keep a resumed workflow's revisions unchanged.
"""
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid5
from .administration import _administer
from .errors import HttpFailure
from .journal import saved

NAMES={'hollywood_create_agent','hollywood_create_room','hollywood_set_role','hollywood_grant_room'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class AdministrationUnconfirmed(RuntimeError):
    pass


class RoomAdministration:
    def __init__(self, *, authority, agent, thread, request, state):
        self.config={'authorityId':authority,'agentId':agent}
        self.thread=thread;self.request=request;self.state=Path(state)
        self.binding={'authority':authority,'agent':agent,'thread':thread}
        self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=asyncio.Lock()

    async def call(self,name,args,call_id):
        async with self.lock:
            actor=await self.request('GET','principals/'+self.config['agentId'])
            if (actor.get('id')!=self.config['agentId'] or actor.get('authority')!=self.config['authorityId']
                    or actor.get('kind')!='agent' or not actor.get('active') or not actor.get('administrator')):
                raise PermissionError('Current authenticated communication administrator required')
            if name=='hollywood_admin_reconcile':
                operation=args['operationId']
                if not isinstance(operation,str) or not operation.startswith('native-admin:'):
                    raise ValueError('Original administrative operation required')
                path=self.state/('workflow-'+str(UUID(operation.removeprefix('native-admin:')))+'.json')
                if not path.exists():raise ValueError('Original administrative operation unavailable')
                record=json.loads(path.read_text())
                if record['operationId']!=operation:raise ValueError('Original administrative operation differs')
            else:
                if name not in NAMES:raise ValueError('Unsupported communication administration tool')
                key=digest([self.thread,call_id]);identity=str(uuid5(UUID(self.config['agentId']),key))
                path=self.state/('workflow-'+identity+'.json');operation='native-admin:'+identity
                record={'operationId':operation,'tool':name,'arguments':args,'state':'intent','binding':self.binding}
                if path.exists():
                    old=json.loads(path.read_text())
                    if any(old[k]!=record[k] for k in ('operationId','tool','arguments','binding')):raise ValueError('Original administrative call changed')
                    record=old
            if record.get('binding')!=self.binding:raise ValueError('Original administration belongs to another native conversation')
            if record['state']=='completed':return record['result']
            if record['state']=='rejected':raise ValueError('Original administrative operation was rejected')
            # At most one unresolved mutation workflow. This durable pointer
            # avoids scanning all historical administrative calls on each tool.
            pending=self.state/'pending.json'
            if pending.exists():
                active=json.loads(pending.read_text())
                if active['binding']!=self.binding:raise ValueError('Pending administration belongs to another native conversation')
                active_path=self.state/('workflow-'+str(UUID(active['operationId'].removeprefix('native-admin:')))+'.json')
                original=json.loads(active_path.read_text())
                if original['state'] in ('completed','rejected'):pending.unlink()
                elif active['operationId']!=record['operationId']:
                    raise AdministrationUnconfirmed('Inspect original administration before another mutation: '+active['operationId'])
            if not path.exists():saved(path,record)
            saved(pending,{'operationId':record['operationId'],'binding':self.binding})
            transport=AdministrationSteps(self,record['operationId'])
            try:
                result=await _administer(transport,record['tool'],record['arguments'],record['operationId'],conversation_actor=actor)
            except Exception as error:
                definite=isinstance(error,(ValueError,PermissionError)) or isinstance(error,HttpFailure) and error.status in (400,403,409,422)
                # A multi-step workflow may already have accepted a principal
                # before a later role mutation is rejected.
                record['state']='rejected' if definite and not transport.accepted_writes else 'unconfirmed'
                record['error']=type(error).__name__;saved(path,record)
                if record['state']=='rejected':pending.unlink(missing_ok=True)
                if record['state']=='unconfirmed':raise AdministrationUnconfirmed('Original administration requires reconciliation: '+record['operationId']) from error
                raise
            result={'operationId':record['operationId'],**result}
            record.update(state='completed',result=result);saved(path,record)
            pending.unlink(missing_ok=True)
            return result


class AdministrationSteps:
    def __init__(self,owner,operation):
        self.owner=owner;self.config=owner.config;self.state=owner.state
        self.operation=operation;self.position=0;self.accepted_writes=False

    async def http(self,method,path,payload=None):
        index=self.position;self.position+=1
        directory=self.state/digest(self.operation);directory.mkdir(mode=0o700,exist_ok=True)
        file=directory/(str(index)+'.json')
        wire={'method':method,'path':path,'body':payload};fingerprint=digest(wire)
        old=json.loads(file.read_text()) if file.exists() else None
        if old and old['wireDigest']!=fingerprint:raise ValueError('Original administrative step changed')
        if old and old['state']=='accepted':
            self.accepted_writes|=method!='GET';return old['result']
        if method=='GET':
            result=await self.owner.request(method,path)
        else:
            if not isinstance(payload,dict) or not payload.get('operationId'):raise ValueError('Stable administrative operation required')
            if old:
                result=await self.reconcile(method,path,payload,fingerprint)
            else:
                saved(file,{'state':'sending','wireDigest':fingerprint,'operationId':payload['operationId']})
                try:result=await self.owner.request(method,path,payload)
                except Exception as error:
                    if isinstance(error,HttpFailure) and error.status in (400,403,409,422):raise
                    result=await self.reconcile(method,path,payload,fingerprint)
            self.accepted_writes=True
        saved(file,{'state':'accepted','wireDigest':fingerprint,'result':result})
        return result

    async def reconcile(self,method,path,payload,fingerprint):
        try:
            receipt=await self.owner.request('GET','administration/commands/'+payload['operationId'])
        except Exception as error:
            # An unavailable/absent read is not proof of rejection or permission
            # to repeat an earlier uncertain write.
            raise AdministrationUnconfirmed('Original administrative acceptance unavailable') from error
        expected={'schema':'hollywood-administrative-command/v1','authorityId':self.config['authorityId'],
                  'actorId':self.config['agentId'],'operationId':payload['operationId'],
                  'method':method,'path':path,'wireDigest':fingerprint}
        if any(receipt.get(k)!=v for k,v in expected.items()):raise AdministrationUnconfirmed('Original administrative receipt mismatch')
        return receipt['acceptedResult']
