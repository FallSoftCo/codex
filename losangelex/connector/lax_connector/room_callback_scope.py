"""Resolve human callback scope from retained, originally accepted room input.

A selected/latest room is not authority. Explicit source IDs resolve only through
this agent's own durable receive journals; ambiguous turns are never guessed.
"""
import json
from uuid import UUID


def explicit_source(agent, identity):
    identity=str(UUID(identity))
    candidates=[]
    for listener in agent.listeners:
        row=listener.journal.read(agent.config['authorityId'],agent.config['agentId'],identity)
        if row is None:continue
        payload=json.loads(row['payload'])
        params=payload['params']
        if params.get('threadId')!=agent.thread:
            raise ValueError('Original native room input binding differs')
        if payload.get('method')=='turn/start':
            if params.get('clientUserMessageId')!=identity:
                raise ValueError('Original human input identity differs')
            context=json.loads(params['additionalContext']['laxRoomMessage']['value'])
            if context.get('schema')!='lax-room-message/v1' or context.get('authorKind')!='human':
                raise ValueError('Original human input provenance differs')
            author=context['authorId'];kind='human'
        elif payload.get('method') in ('hollywood/agentMessage','thread/inject_items'):
            items=params.get('items',[])
            if len(items)!=1 or items[0].get('type')!='agent_message' or items[0].get('recipient')!=agent.config['agentId']:
                raise ValueError('Original native peer input binding differs')
            item=items[0]
            if item.get('id')!='amsg_'+identity or len(item.get('content',[]))!=1:
                raise ValueError('Original peer event identity differs')
            context=json.loads(item['content'][0]['text']);author=item['author'];kind='agent'
        else:continue
        if (context.get('eventId')!=identity or context.get('authorityId')!=agent.config['authorityId']
                or context.get('roomId')!=listener.room):
            raise ValueError('Original room input provenance differs')
        # Hollywood resolves the human through accepted delegation. The connector
        # preserves peer authorship and never invents a human decision owner.
        candidates.append({'id':identity,'room':listener.room,'author':author,
                           'authority':context['authorityId'],'data':{'authorKind':kind}})
    if len(candidates)!=1:
        raise ValueError('Question source must identify one original room input in a subscribed room')
    return candidates[0]


def resolve(agent,params):
    if params.get('sourceEventId'):
        return explicit_source(agent,params['sourceEventId'])
    turn=params['turnId'];rooms=agent.turn_input_rooms.get(turn,set())
    if len(rooms)>1:
        raise ValueError('Multiple rooms contributed to this native turn; explicit sourceEventId required')
    source=agent.turn_sources.get(turn)
    if source is None:raise ValueError('Native callback has no original human room input')
    return source
