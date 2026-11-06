"""Validate retained user work before any native role/checkpoint mutation."""


def verify_retained_source(event, *, authority, room, lead, handover=None):
    if (event.get('authority')!=authority or event.get('room')!=room
            or event.get('data',{}).get('authorKind')!='human' or event.get('kind') not in ('message','request')):
        raise ValueError('Retained work requires its original canonical human source and project')
    if lead in event.get('data',{}).get('conversationRecipients',[]):return
    if (not isinstance(handover,dict) or handover.get('version')!=1
            or handover.get('mode')!='lead' or handover.get('leadAgentId')!=lead
            or handover.get('roomId')!=room or type(handover.get('revision')) is not int
            or handover['revision']<1 or type(handover.get('inputAfterSeq')) is not int
            or type(event.get('seq')) is not int or not 0<event['seq']<=handover['inputAfterSeq']
            or event.get('audience')!='room'):
        raise ValueError('Original work did not address this lead or a reviewed pre-policy public-work handover')
