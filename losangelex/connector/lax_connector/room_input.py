"""Canonical human room input through Codex's existing start-or-steer API.

The caller authenticates the Hollywood feed and owns its durable receive cursor.
This adapter does not claim work, start a process, retry a submission, change
models/settings, or convert agent content into human authority.
"""
import json
from uuid import UUID


def human_input(event, *, authority_id, agent_id, thread_id):
    authority_id=str(UUID(authority_id));agent_id=str(UUID(agent_id))
    if not isinstance(thread_id,str) or not thread_id:
        raise ValueError('Existing agent native thread required')
    if event.get('authority')!=authority_id:
        raise ValueError('Message belongs to another authority')
    event_id=str(UUID(event['id']));author=str(UUID(event['author']));room=str(UUID(event['room']))
    if event.get('kind') not in ('message','request') or event.get('data',{}).get('authorKind')!='human':
        raise ValueError('Authenticated human room input required')
    if event.get('data',{}).get('conversationVersion')!=1 or agent_id not in event['data'].get('conversationRecipients',[]):
        raise ValueError('Agent was not a recipient when the message was accepted')
    if event.get('audience') not in ('room','direct') or event['audience']=='direct' and event.get('recipient')!=agent_id:
        raise ValueError('Room message audience differs')
    body=event.get('body')
    if not isinstance(body,str) or not body.strip():
        raise ValueError('Message body required')
    metadata={'schema':'lax-room-message/v1','authorityId':authority_id,'roomId':room,
              'eventId':event_id,'authorId':author,'authorKind':'human','audience':event['audience'],
              'sourceEventId':event.get('source'),'sharedConversation':True,
              'instruction':'This human message was delivered to all agent members of this room. If already working, assess relevance before changing course. Coordinate with peers; do not assume exclusive task ownership.'}
    return {'threadId':thread_id,'clientUserMessageId':event_id,
            'input':[{'type':'text','text':body,'text_elements':[]}],
            'turnTrigger':'hollywood.human_room',
            'additionalContext':{'laxRoomMessage':{'kind':'application','value':json.dumps(metadata,sort_keys=True)}}}


async def submit_human(rpc,event,*,authority_id,agent_id,thread_id):
    # start_or_steer_turn in native Core serializes the idle/busy decision.
    # A lost ACK must be reconciled by original clientUserMessageId in native
    # history. Neither a timeout nor a cursor reread authorizes another call.
    return await rpc.call('turn/start',human_input(event,authority_id=authority_id,agent_id=agent_id,thread_id=thread_id))


def peer_context(event, *, authority_id, agent_id, thread_id):
    """Retain an ordinary peer contribution without starting an inference."""
    authority_id=str(UUID(authority_id));agent_id=str(UUID(agent_id))
    if not isinstance(thread_id,str) or not thread_id or event.get('authority')!=authority_id:
        raise ValueError('Existing agent thread in the exact authority required')
    data=event.get('data',{})
    if data.get('authorKind')!='agent' or data.get('conversationVersion')!=1 or agent_id not in data.get('conversationRecipients',[]):
        raise ValueError('Authenticated peer input for this member required')
    if event.get('audience') not in ('room','direct') or event['audience']=='direct' and event.get('recipient')!=agent_id:
        raise ValueError('Peer message audience differs')
    if event.get('kind') not in ('message','request','result','question'):
        raise ValueError('Explicit peer requests need native start-or-steer admission')
    event_id=str(UUID(event['id']));author=str(UUID(event['author']));room=str(UUID(event['room']))
    if author==agent_id:raise ValueError('Own publications are not new input')
    body=event.get('body')
    if not isinstance(body,str) or not body.strip():raise ValueError('Message body required')
    content={'authorityId':authority_id,'roomId':room,'eventId':event_id,
             'sourceEventId':event.get('source'),'audience':event['audience'],
             'kind':event['kind'],'expectsReply':bool(data.get('expectsReply')),'body':body}
    return {'threadId':thread_id,'items':[{'type':'agent_message','id':'amsg_'+event_id,
            'author':author,'recipient':agent_id,'content':[{'type':'input_text','text':json.dumps(content,sort_keys=True)}]}]}


async def retain_peer(rpc,event,*,authority_id,agent_id,thread_id):
    # Existing native history-only API checkpoints input without sampling.
    # Never masquerade peer observations as human turn/start or tool outputs.
    return await rpc.call('thread/inject_items',peer_context(event,authority_id=authority_id,agent_id=agent_id,thread_id=thread_id))


async def submit_peer(rpc,event,*,authority_id,agent_id,thread_id):
    """Explicitly addressed peer input keeps native agent authorship."""
    if event.get('recipient')!=agent_id:
        raise ValueError('Only explicitly addressed peer input starts a turn')
    # Validate the canonical actor/audience without converting to human input.
    context=peer_context(event,authority_id=authority_id,agent_id=agent_id,thread_id=thread_id)
    item=context['items'][0];data=json.loads(item['content'][0]['text'])
    return await rpc.call('hollywood/agentMessage',{
        'threadId':thread_id,'authorityId':data['authorityId'],'roomId':data['roomId'],
        'eventId':data['eventId'],'authorId':item['author'],'recipientId':agent_id,
        'body':data['body'],'audience':data['audience'],'kind':data['kind'],
        'sourceEventId':data['sourceEventId'],'expectsReply':False})
