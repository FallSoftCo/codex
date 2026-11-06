"""Agent-authored room tools bound to a persistent native thread, not a job.

These are communication primitives for the conversational-runtime candidate.
They deliberately do not expose the old execution-claim/admission workflow.
"""
from .runtime_files import state_directory
import asyncio,hashlib,json,socket
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID,uuid5
from .journal import saved
from .errors import HttpFailure
from .room_reply_window import ReplyContextChanged


def definition(name,description,properties,required):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}

STRING={'type':'string'}
TOOLS=[
    definition('hollywood_context','Read your identity and the real participants of an authorized room. Room membership is communication, not task ownership.',{'roomId':STRING},['roomId']),
    definition('hollywood_read_room','Read canonical recent room conversation or explicitly requested execution activity.',{'roomId':STRING,'after':{'type':'integer','minimum':0},'before':{'type':'integer','minimum':1},'limit':{'type':'integer','minimum':1,'maximum':100},'view':{'type':'string','enum':['conversation','coordination','activity','all']}},['roomId']),
    definition('hollywood_publish','Publish in your own agent identity. Answers/progress preserve original room/source/audience. Explicit recipientId addresses a peer; direct is private. Omitted sourceEventId defaults to the unambiguous original source. For genuinely NEW semantic peer coordination only, sourceEventId:null with phase message deliberately creates no source reference; it is not permission to copy private input or mark an owed answer delivered. Accepted is stored, never task claimed/completed. Do not publish routine acknowledgements.',{'roomId':STRING,'body':STRING,'recipientId':STRING,'sourceEventId':{'type':['string','null']},'responsePhase':{'type':'string','enum':['message','update','answer','blocked']},'audience':{'type':'string','enum':['room','direct']}},['roomId','body','audience','responsePhase']),
]

from .native_tool_declarations import TOOLS as NATIVE_TOOLS
from .room_administration import RoomAdministration, AdministrationUnconfirmed, NAMES as ADMIN_NAMES, HOST_TOOL, FACTORY_TOOL
from .room_inspect import READ_NAMES, inspect_metadata
TOOLS += [tool for tool in NATIVE_TOOLS if tool['name'] in ADMIN_NAMES | READ_NAMES]
TOOLS += [definition(HOST_TOOL,'Provision an already enrolled and joined agent on this configured local host. Requires current communication administrator and verified local sudo; does not create a replacement identity, send instructions or claim task completion.',{'agentId':STRING,'roomId':STRING},['agentId','roomId'])]
TOOLS += [definition(FACTORY_TOOL,'Initialize or reconcile this enrolled environment\'s deterministic room-origin agent on the EXISTING shared native app-server. Original credentials/spec/thread are retained. Never replay old room inputs, create another daemon, or treat allocation as native readiness.',{'roomId':STRING},['roomId'])]
TOOLS += [definition('hollywood_admin_reconcile',
    'Inspect and continue the exact original administrative workflow after an unknown result. Never creates a replacement operation or repeats an uncertain write. Requires current administrator authority.',
    {'operationId':STRING},['operationId'])]


class RoomTools:
    def __init__(self,*,authority_id,agent_id,thread_id,request,state,source_for_turn=None,host_config=None,on_membership=None, conversation_io=None,native_state_view=None,session_supervisor=None):
        self.authority=str(UUID(authority_id));self.agent=str(UUID(agent_id));self.thread=thread_id
        self.request=request;self.state=Path(state);state_directory(self.state, parents=True,exist_ok=True)
        self.conversation_io=conversation_io
        self.native_state_view=native_state_view
        self.source_for_turn=source_for_turn
        self.on_membership=on_membership
        self.publish_lock=asyncio.Lock()
        self.reply_window=None
        self.project=None
        self.administration=RoomAdministration(authority=self.authority,agent=self.agent,thread=self.thread,request=request,state=self.state/'administration',host_config=host_config,session_supervisor=session_supervisor)

    async def call(self,method,params):
        try:
            return await self._call(method,params)
        except ReplyContextChanged as error:
            # This tool result is the model's actual opportunity to reconsider.
            self.reply_window.seen(params.get('turnId'), error.snapshot)
            return {'success':False,'contentItems':[{'type':'inputText','text':json.dumps({
                **error.snapshot,'next':'Not posted. Compare your draft with these peer replies. '
                'Publish only a useful addition with the original source, or finish without publishing. '
                'No acknowledgement or duplicate recap is needed.'})}]}
        except HttpFailure as error:
            return {"success":False,"contentItems":[{"type":"inputText","text":json.dumps(error.public_details())}]}
        except AdministrationUnconfirmed as error:
            return {"success":False,"contentItems":[{"type":"inputText","text":json.dumps({"error":str(error),"next":"Use hollywood_admin_reconcile with the original operationId. Do not create a replacement administrative call."})}]}
        except (ValueError, PermissionError) as error:
            return {"success":False,"contentItems":[{"type":"inputText","text":json.dumps({"error":str(error),"next":"Correct the validated input; do not repeat an uncertain publication."})}]}

    async def _call(self,method,params):
        if method!='item/tool/call' or params.get('threadId')!=self.thread:
            raise ValueError('Tool callback does not belong to this native agent thread')
        name=params['tool'];args=params['arguments']
        if isinstance(args,str):args=json.loads(args)
        if not isinstance(args,dict):raise ValueError('Tool arguments must be an object')
        from .project_tools import NAMES as PROJECT_NAMES
        if name in PROJECT_NAMES:
            if not self.project:raise ValueError('This native context has no reviewed project-lead binding')
            result=await self.project.call(name,args,params['callId'],params.get('turnId'))
            return {'success':True,'contentItems':[{'type':'inputText','text':json.dumps(result,default=str)}]}
        if name in ADMIN_NAMES|{HOST_TOOL,FACTORY_TOOL} or name=='hollywood_admin_reconcile':
            result=await self.administration.call(name,args,params['callId'])
            if self.on_membership:self.on_membership()
            return {'success':True,'contentItems':[{'type':'inputText','text':json.dumps(result,default=str)}]}
        if name in READ_NAMES:
            result=await inspect_metadata(self.request,name,args)
            if name=='hollywood_room_info' and self.conversation_io:
                result={**result,'ownReplyState':self.conversation_io.reply_status(args['roomId'])}
            if name=='hollywood_room_info' and self.native_state_view:
                result={**result,'ownNativeState':self.native_state_view(args['roomId'])}
            return {'success':True,'contentItems':[{'type':'inputText','text':json.dumps(result,default=str)}]}
        room=str(UUID(args['roomId']))
        if name=='hollywood_context':
            value=await self.request('GET','rooms/'+room)
            if value['authorityId']!=self.authority:raise ValueError('Room authority changed')
            result={'self':{'authorityId':self.authority,'agentId':self.agent,'nativeThread':self.thread},
                    'room':value['room'],'participants':value['actors'],
                    'communicationIsNotExecution':True,
                    'localHost':{'hostname':socket.gethostname(),
                                 'hostId':self.administration.host_config.get('hostId'),
                                 'workspace':self.administration.host_config.get('workspace')}}
            if self.project:result['nativeState']=value.get('nativeState')
            if self.conversation_io:result['ownReplyState']=self.conversation_io.reply_status(room)
            if self.native_state_view:result['ownNativeState']=self.native_state_view(room)
        elif name=='hollywood_read_room':
            if 'after' in args and 'before' in args:raise ValueError('Choose one history direction')
            query={k:args[k] for k in ('after','before','limit','view') if k in args}
            project=self.project and self.project.ledger.room==room
            query.setdefault('limit',12 if project else 30)
            query.setdefault('view','coordination' if project and not self.project.ledger.is_lead else 'conversation')
            if 'after' not in query:query.setdefault('before',9007199254740991)
            result=await self.request('GET','rooms/'+room+'/history?'+urlencode(query))
            if result['authorityId']!=self.authority or result['roomId']!=room:raise ValueError('Room history scope changed')
        elif name=='hollywood_publish':
            call=params['callId'];key=hashlib.sha256((self.thread+'\0'+call).encode()).hexdigest()
            async with self.publish_lock:
                result=await self.publish(room,args,key,turn=params.get('turnId'))
        else:raise ValueError('Unknown conversational tool')
        return {'success':True,'contentItems':[{'type':'inputText','text':json.dumps(result,default=str)}]}

    async def publish(self,room,args,key,*,turn=None,coordinate=None):
        body=args.get('body')
        if not isinstance(body,str) or not body.strip() or len(body.encode())>6000:raise ValueError('Message must contain 1..6000 UTF-8 bytes')
        audience=args.get('audience')
        if audience not in ('room','direct'):raise ValueError('Explicit message audience required')
        path=self.state/(key+'.json');prior=json.loads(path.read_text()) if path.exists() else None
        payload={'operationId':'native-room:'+str(uuid5(UUID(self.agent),key)),'kind':'message','body':body,'audience':audience}
        if args.get('coordination') is not None:payload['coordination']={'outcome':None,'originEventId':None,'evidence':[],**args['coordination']}
        for field in ('recipientId','sourceEventId'):
            if args.get(field):payload[field]=str(UUID(args[field]))
        if args.get('responsePhase') is not None:
            if args['responsePhase'] not in ('message','update','answer','blocked'):raise ValueError('Unknown response phase')
            payload['responsePhase']=args['responsePhase']
        semantic_new = 'sourceEventId' in args and args['sourceEventId'] is None
        if semantic_new and args.get('responsePhase') != 'message':
            raise ValueError('Explicit no-source is only new semantic conversation, not an answer/progress bypass')
        if not args.get('sourceEventId') and not semantic_new:
            source=(prior.get('payload',{}).get('sourceEventId') if prior else ((self.conversation_io.source(turn,room) or {}).get('id') if self.conversation_io else self.source_for_turn(turn) if self.source_for_turn else None))
            if source:payload['sourceEventId']=str(UUID(source))
        if payload.get('recipientId')==self.agent and not (self.project and self.project.ledger.is_lead and payload.get('coordination',{}).get('type')=='wake'):raise ValueError('Self-publication is not new input')
        if audience=='direct' and not payload.get('recipientId'):raise ValueError('Private message requires recipient')
        if not prior and self.conversation_io and payload.get('sourceEventId'):
            source = self.conversation_io.input_event(payload['sourceEventId'])
            if source and args.get('responsePhase') in ('answer','update','blocked') and room != source['room']:
                raise ValueError('Source-bound answer/progress belongs to its original room; no cross-room fallback')
            if source and source.get('audience') == 'direct':
                original = {source.get('author'), source.get('recipient')}
                if (None in original or room != source['room'] or audience != 'direct'
                        or {self.agent, payload.get('recipientId')} != original):
                    raise ValueError('Private source requires a direct reply to its original counterpart '
                                     'in the original room. No HTTP publication was dispatched; '
                                     'correct the audience/source in a new native tool call.')
        if prior and prior.get('payload',{}).get('replyCheck') is not None:
            payload['replyCheck']=prior['payload']['replyCheck']
        elif (not prior and self.reply_window and not payload.get('recipientId')
                and (coordinate is True or coordinate is None and payload.get('responsePhase') in ('message','update','answer'))
                and self.conversation_io and payload.get('sourceEventId')):
            source=self.conversation_io.input_event(payload['sourceEventId'])
            if source:
                condition=await self.reply_window.condition(key,source,turn)
                if condition is not None:payload['replyCheck']=condition
        fingerprint=hashlib.sha256(json.dumps({'room':room,'payload':payload},sort_keys=True).encode()).hexdigest()
        if prior and prior['fingerprint']!=fingerprint:raise ValueError('Original native call changed')
        if prior and prior['state']=='accepted':
            event = prior['receipt']['event']
            canonical = self.conversation_io and event.get('id') and self.conversation_io.observe_own_reply(event)
            if self.conversation_io and turn and payload.get('responsePhase') in ('answer','blocked'):
                self.conversation_io.publication(turn,payload.get('sourceEventId'),key,room,'accepted',phase=payload['responsePhase'],event_id=event['id'] if canonical else None)
            return prior['receipt']
        if prior and prior['state']=='reconsider':raise ReplyContextChanged(prior['snapshot'])
        if prior and prior['state']=='rejected':raise HttpFailure(prior['error']['status'],prior['error']['message'])
        track = self.conversation_io and turn and payload.get('responsePhase') in ('answer','blocked')
        if track:self.conversation_io.publication(turn,payload.get('sourceEventId'),key,room,'attempting',phase=payload['responsePhase'])
        if not prior:
            saved(path,{'state':'sending','fingerprint':fingerprint,'room':room,'payload':payload})
            try:
                result=await self.request('POST','rooms/'+room+'/messages',payload)
            except HttpFailure as error:
                if error.status in (400,403,409):
                    saved(path,{'state':'rejected','fingerprint':fingerprint,'room':room,'payload':payload,'error':error.public_details()})
                    if track:self.conversation_io.publication(turn,payload.get('sourceEventId'),key,room,'rejected',phase=payload['responsePhase'])
                    raise
                result=await self.request('GET','commands/'+payload['operationId'])
            except Exception:
                # Reconcile the original accepted command; never resend after a
                # lost ACK. A 404 here remains unconfirmed, not safe-to-repeat.
                result=await self.request('GET','commands/'+payload['operationId'])
        else:result=await self.request('GET','commands/'+payload['operationId'])
        if (result.get('accepted') is False and result.get('mayApply') is False
                and result.get('code')=='REPLY_CONTEXT_CHANGED'):
            if (result.get('roomId')!=room or result.get('sourceEventId')!=payload.get('sourceEventId')
                    or not payload.get('replyCheck') or type(result.get('observedThrough')) is not int
                    or result['observedThrough'] < payload['replyCheck']['observedThrough']
                    or not isinstance(result.get('peerReplies'),list) or not 1<=len(result['peerReplies'])<=6):
                raise ValueError('Conditional reply context scope changed')
            saved(path,{'state':'reconsider','fingerprint':fingerprint,'room':room,'payload':payload,'snapshot':result})
            if track:self.conversation_io.publication(turn,payload.get('sourceEventId'),key,room,'rejected',phase=payload['responsePhase'])
            raise ReplyContextChanged(result)
        event=result.get('event')
        if (not result.get('accepted') or not event or event['authority']!=self.authority
            or event['author']!=self.agent or event['room']!=room or event.get('kind')!='message'
            or event.get('body')!=payload['body'] or event.get('audience')!=payload['audience']
            or event.get('recipient')!=payload.get('recipientId') or event.get('source')!=payload.get('sourceEventId')
            or event.get('data',{}).get('coordination')!=payload.get('coordination')
            or result.get('deliveries')!=[]
            or payload.get('responsePhase') is not None and event.get('data',{}).get('responsePhase')!=payload['responsePhase']):
            raise ValueError('Original publication acceptance unavailable or mismatched')
        saved(path,{'state':'accepted','fingerprint':fingerprint,'room':room,'payload':payload,'receipt':result})
        canonical = self.conversation_io and event.get('id') and self.conversation_io.observe_own_reply(event)
        if track:self.conversation_io.publication(turn,payload.get('sourceEventId'),key,room,'accepted',phase=payload['responsePhase'],event_id=event['id'] if canonical else None)
        return result
