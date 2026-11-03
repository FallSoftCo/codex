"""Frozen original human renderer from published SDK239 (before policy change)."""
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
