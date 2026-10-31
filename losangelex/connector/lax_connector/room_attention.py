"""Return a human decision to its original native RPC, using room events to wake."""
import asyncio
import json
from uuid import UUID, uuid5
from .journal import saved
from .errors import HttpFailure

QUESTION={'hollywood/question','item/tool/requestUserInput'}
APPROVAL={'item/commandExecution/requestApproval','item/fileChange/requestApproval'}


class RoomAttention:
    def __init__(self,agent):
        self.agent=agent;self.pending={};self.by_rpc={}

    async def observe(self,event):
        identity=event.get('data',{}).get('attentionId')
        if identity in self.pending:self.pending[identity]['changed'].set()

    async def wait(self,method,params):
        c=self.agent;turn=params['turnId'];slot=str(params.get('itemId',params['_rpcRequestId']))
        if params.get('threadId')!=c.thread or method not in QUESTION|APPROVAL:
            raise ValueError('Original native callback required')
        source=c.turn_sources.get(turn)
        if source is None:raise ValueError('Native callback has no original human room input')
        identity=str(uuid5(UUID(c.config['agentId']),json.dumps([c.thread,turn,slot,method])))
        if method in QUESTION:
            request={'questions':params['questions'],'isBlocking':True}
            summary='\n'.join(q['question'] for q in params['questions'])
        else:
            item=c.native_items.get(params.get('itemId'),{})
            request={'command':params.get('command'),'cwd':params.get('cwd'),'reason':params.get('reason'),'changes':item.get('changes')}
            summary='Approval required: '+(params.get('command') or 'file changes')
        payload={'id':identity,'conversationVersion':1,'roomId':source['room'],'sourceEventId':source['id'],
            'nativeThread':c.thread,'nativeTurn':turn,'nativeSlot':slot,'method':method,'summary':summary,'request':request}
        path=c.state/('conversation-attention-'+identity+'.json')
        if path.exists():raise RuntimeError('Original callback exists; reconcile without replay')
        entry={'changed':asyncio.Event(),'payload':payload,'path':path,'turn':turn,'submission_done':asyncio.Event()}
        self.pending[identity]=entry;self.by_rpc[str(params['_rpcRequestId'])]=identity
        saved(path,{'state':'creating','payload':payload})
        try:
            receipt=await c.http('POST','attention',payload)
        except HttpFailure as error:
            if error.status in (400,403,409,422):raise
            receipt=await c.http('GET','attention/'+identity+'?roomId='+source['room'])
        except (OSError,asyncio.TimeoutError):
            receipt=await c.http('GET','attention/'+identity+'?roomId='+source['room'])
        if (receipt['scope'].get('conversationVersion')!=1 or receipt['scope']['nativeThread']!=c.thread
            or receipt['scope']['nativeTurn']!=turn or receipt['scope']['sourceEventId']!=source['id']):
            raise ValueError('Attention receipt differs from original callback')
        entry['scope']=receipt['scope'];saved(path,{'state':'waiting','payload':payload,'receipt':receipt})
        while True:
            entry['changed'].clear()
            current=await c.http('GET','attention/'+identity+'?roomId='+source['room'])
            if current['scope']!=entry['scope']:raise ValueError('Original callback scope changed')
            if turn in c.finished_turns:
                raise RuntimeError('Native turn ended before callback response')
            if current['attention']['state']=='response_submitted':
                response=current['attention']['response']
                saved(path,{'state':'response_ready','payload':payload,'receipt':current})
                entry['response_ready']=True
                return response
            if current['attention']['state']!='pending':raise RuntimeError('Native callback no longer pending')
            # SSE response event wakes this callback. No timed model/HTTP polling.
            await entry['changed'].wait()

    async def submitted(self,method,params,success):
        identity=self.by_rpc.pop(str(params['_rpcRequestId']),None)
        if identity is None:return
        entry=self.pending.get(identity)
        if entry is None:return
        try:
            if not success or 'scope' not in entry:return
            result=await self.agent.http('POST','attention/'+identity+'/acknowledge',{
                'operationId':'native-response-written:'+identity,'scope':entry['scope'],'state':'native_submitted'})
            saved(entry['path'],{'state':'native_response_written','payload':entry['payload'],'receipt':result})
        finally:
            entry['submission_done'].set()

    async def finish(self,turn):
        for identity,entry in list(self.pending.items()):
            if entry['turn']!=turn:continue
            entry['changed'].set()
            if entry.get('response_ready'):await entry['submission_done'].wait()
            if 'scope' not in entry:continue
            current=await self.agent.http('GET','attention/'+identity+'?roomId='+entry['scope']['roomId'])
            state=current['attention']['state']
            target='closed' if state=='native_submitted' else 'expired'
            if state in ('pending','response_submitted','native_submitted'):
                result=await self.agent.http('POST','attention/'+identity+'/acknowledge',{
                    'operationId':'native-turn-ended:'+identity,'scope':entry['scope'],'state':target})
                saved(entry['path'],{'state':target,'payload':entry['payload'],'receipt':result})
            self.pending.pop(identity,None)
