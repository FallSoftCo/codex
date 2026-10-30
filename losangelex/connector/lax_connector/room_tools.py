"""Agent-authored room tools bound to a persistent native thread, not a job.

These are communication primitives for the conversational-runtime candidate.
They deliberately do not expose the old execution-claim/admission workflow.
"""
import asyncio,hashlib,json
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID,uuid5
from .journal import saved
from .errors import HttpFailure


def definition(name,description,properties,required):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}

STRING={'type':'string'}
TOOLS=[
    definition('hollywood_context','Read your identity and the real participants of an authorized room. Room membership is communication, not task ownership.',{'roomId':STRING},['roomId']),
    definition('hollywood_read_room','Read canonical recent room conversation or explicitly requested execution activity.',{'roomId':STRING,'after':{'type':'integer','minimum':0},'before':{'type':'integer','minimum':1},'limit':{'type':'integer','minimum':1,'maximum':100},'view':{'type':'string','enum':['conversation','activity','all']}},['roomId']),
    definition('hollywood_publish','Publish in your own agent identity. A public message is shared context; recipientId explicitly addresses a peer. Direct audience is private. Accepted means stored, not answered. Do not publish routine acknowledgements.',{'roomId':STRING,'body':STRING,'recipientId':STRING,'sourceEventId':STRING,'audience':{'type':'string','enum':['room','direct']}},['roomId','body','audience']),
]

class RoomTools:
    def __init__(self,*,authority_id,agent_id,thread_id,request,state):
        self.authority=str(UUID(authority_id));self.agent=str(UUID(agent_id));self.thread=thread_id
        self.request=request;self.state=Path(state);self.state.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.publish_lock=asyncio.Lock()

    async def call(self,method,params):
        try:
            return await self._call(method,params)
        except HttpFailure as error:
            return {"success":False,"contentItems":[{"type":"inputText","text":json.dumps(error.public_details())}]}
        except ValueError as error:
            return {"success":False,"contentItems":[{"type":"inputText","text":json.dumps({"error":str(error),"next":"Correct the validated input; do not repeat an uncertain publication."})}]}

    async def _call(self,method,params):
        if method!='item/tool/call' or params.get('threadId')!=self.thread:
            raise ValueError('Tool callback does not belong to this native agent thread')
        name=params['tool'];args=params['arguments']
        if isinstance(args,str):args=json.loads(args)
        if not isinstance(args,dict):raise ValueError('Tool arguments must be an object')
        room=str(UUID(args['roomId']))
        if name=='hollywood_context':
            value=await self.request('GET','rooms/'+room)
            if value['authorityId']!=self.authority:raise ValueError('Room authority changed')
            result={'self':{'authorityId':self.authority,'agentId':self.agent,'nativeThread':self.thread},
                    'room':value['room'],'participants':value['actors'],
                    'communicationIsNotExecution':True}
        elif name=='hollywood_read_room':
            if 'after' in args and 'before' in args:raise ValueError('Choose one history direction')
            query={k:args[k] for k in ('after','before','limit','view') if k in args}
            query.setdefault('limit',30);query.setdefault('view','conversation')
            if 'after' not in query:query.setdefault('before',9007199254740991)
            result=await self.request('GET','rooms/'+room+'/history?'+urlencode(query))
            if result['authorityId']!=self.authority or result['roomId']!=room:raise ValueError('Room history scope changed')
        elif name=='hollywood_publish':
            call=params['callId'];key=hashlib.sha256((self.thread+'\0'+call).encode()).hexdigest()
            async with self.publish_lock:
                result=await self.publish(room,args,key)
        else:raise ValueError('Unknown conversational tool')
        return {'success':True,'contentItems':[{'type':'inputText','text':json.dumps(result,default=str)}]}

    async def publish(self,room,args,key):
        body=args.get('body')
        if not isinstance(body,str) or not body.strip() or len(body.encode())>6000:raise ValueError('Message must contain 1..6000 UTF-8 bytes')
        audience=args.get('audience')
        if audience not in ('room','direct'):raise ValueError('Explicit message audience required')
        payload={'operationId':'native-room:'+str(uuid5(UUID(self.agent),key)),'kind':'message','body':body,'audience':audience}
        for field in ('recipientId','sourceEventId'):
            if args.get(field):payload[field]=str(UUID(args[field]))
        if payload.get('recipientId')==self.agent:raise ValueError('Self-publication is not new input')
        if audience=='direct' and not payload.get('recipientId'):raise ValueError('Private message requires recipient')
        path=self.state/(key+'.json');prior=json.loads(path.read_text()) if path.exists() else None
        fingerprint=hashlib.sha256(json.dumps({'room':room,'payload':payload},sort_keys=True).encode()).hexdigest()
        if prior and prior['fingerprint']!=fingerprint:raise ValueError('Original native call changed')
        if prior and prior['state']=='accepted':return prior['receipt']
        if prior and prior['state']=='rejected':raise HttpFailure(prior['error']['status'],prior['error']['message'])
        if not prior:
            saved(path,{'state':'sending','fingerprint':fingerprint,'room':room,'payload':payload})
            try:
                result=await self.request('POST','rooms/'+room+'/messages',payload)
            except HttpFailure as error:
                if error.status in (400,403,409):
                    saved(path,{'state':'rejected','fingerprint':fingerprint,'room':room,'payload':payload,'error':error.public_details()})
                    raise
                result=await self.request('GET','commands/'+payload['operationId'])
            except Exception:
                # Reconcile the original accepted command; never resend after a
                # lost ACK. A 404 here remains unconfirmed, not safe-to-repeat.
                result=await self.request('GET','commands/'+payload['operationId'])
        else:result=await self.request('GET','commands/'+payload['operationId'])
        event=result.get('event')
        if not result.get('accepted') or not event or event['authority']!=self.authority or event['author']!=self.agent or event['room']!=room:
            raise ValueError('Original publication acceptance unavailable or mismatched')
        saved(path,{'state':'accepted','fingerprint':fingerprint,'room':room,'payload':payload,'receipt':result})
        return result
