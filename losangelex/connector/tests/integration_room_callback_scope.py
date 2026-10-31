"""Resolve cross-room questions from actual durable receive journals, not focus."""
import json,os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from lax_connector.room_receive import RoomReceiveJournal
from lax_connector.room_input import human_input,peer_context
from lax_connector.room_callback_scope import resolve
root=Path(os.environ['ROOM_SCOPE_EVIDENCE']);root.mkdir(mode=0o700)
authority,agent,author,rooma,roomb,eventa,eventb=[str(uuid4()) for _ in range(7)]
thread='owned-native-thread';listeners=[]
for room,event in ((rooma,eventa),(roomb,eventb)):
 journal=RoomReceiveJournal(root/(room+'.sqlite'))
 value={'id':event,'authority':authority,'room':room,'author':author,'kind':'message','audience':'room','body':'Owned synthetic scope check','data':{'authorKind':'human','conversationVersion':1,'conversationRecipients':[agent]}}
 params=human_input(value,authority_id=authority,agent_id=agent,thread_id=thread)
 journal.stage(authority=authority,agent=agent,event=event,thread=thread,seq=1,payload={'method':'turn/start','params':params})
 listeners.append(SimpleNamespace(journal=journal,room=room))
owner=SimpleNamespace(config={'authorityId':authority,'agentId':agent},thread=thread,listeners=listeners,turn_input_rooms={'turn':{rooma,roomb}},turn_sources={'turn':{'id':eventb,'room':roomb}})
try:
 try:resolve(owner,{'turnId':'turn'})
 except ValueError:pass
 else:raise AssertionError('Ambiguous turn silently chose latest room')
 assert resolve(owner,{'turnId':'turn','sourceEventId':eventa})['room']==rooma
 assert resolve(owner,{'turnId':'turn','sourceEventId':eventb})['room']==roomb
 try:resolve(owner,{'turnId':'turn','sourceEventId':str(uuid4())})
 except ValueError:pass
 else:raise AssertionError('Unknown source accepted')
 peer=str(uuid4());peer_author=str(uuid4())
 value={'id':peer,'authority':authority,'room':roomb,'author':peer_author,'recipient':agent,'kind':'message','audience':'direct','source':eventa,'body':'Owned delegated question scope','data':{'authorKind':'agent','conversationVersion':1,'conversationRecipients':[agent]}}
 params=peer_context(value,authority_id=authority,agent_id=agent,thread_id=thread)
 listeners[1].journal.stage(authority=authority,agent=agent,event=peer,thread=thread,seq=2,payload={'method':'hollywood/agentMessage','params':params})
 resolved=resolve(owner,{'turnId':'turn','sourceEventId':peer})
 assert resolved['id']==peer and resolved['author']==peer_author and resolved['data']['authorKind']=='agent' and resolved['room']==roomb
 for listener in listeners:
  listener.journal.close();listener.journal=RoomReceiveJournal(root/(listener.room+'.sqlite'))
 assert resolve(owner,{'turnId':'turn','sourceEventId':eventa})['room']==rooma
 result={'state':'passed','latestRoomNotUsedForAmbiguousQuestion':True,'explicitOriginalSourceRoutesBothRooms':True,'unknownSourceRejected':True,'delegatedPeerAuthorshipPreserved':True,'restartRetainsOriginalProvenance':True,'modelCalls':0,'productionChanged':False}
 (root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
finally:
 for listener in listeners:listener.journal.close()
