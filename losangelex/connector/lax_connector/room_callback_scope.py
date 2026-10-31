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
        if payload.get('method')!='turn/start':continue
        params=payload['params']
        if params.get('threadId')!=agent.thread or params.get('clientUserMessageId')!=identity:
            raise ValueError('Original native human input binding differs')
        context=json.loads(params['additionalContext']['laxRoomMessage']['value'])
        if (context.get('schema')!='lax-room-message/v1' or context.get('eventId')!=identity
                or context.get('authorityId')!=agent.config['authorityId']
                or context.get('roomId')!=listener.room or context.get('authorKind')!='human'):
            raise ValueError('Original human input provenance differs')
        candidates.append({'id':identity,'room':listener.room,'author':context['authorId'],
                           'authority':context['authorityId'],'data':{'authorKind':'human'}})
    if len(candidates)!=1:
        raise ValueError('Question source must identify one original human input in a subscribed room')
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
