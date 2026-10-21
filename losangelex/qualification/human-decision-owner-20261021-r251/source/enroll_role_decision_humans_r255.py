"""Enroll regular QA human B; role decision owner A remains explicit bootstrap Owner."""
import json,secrets,time
from pathlib import Path
from uuid import uuid4
from lax_connector.host import request
from lax_connector.journal import saved
from lax_connector.collaboration_capture import administrative_put
from hollywood_backbone.store import Store
root=Path('/var/lib/lax-role-decision-owner-20261020-r251');base=root/'role-owner-r255'
arm=json.loads((base/'public.json').read_text());plan=json.loads((base/'installation-intent.json').read_text())
p=base/'source-human.json';assert not p.exists()
identity={'principalId':str(uuid4()),'token':secrets.token_urlsafe(40)};saved(p,identity)
api=lambda method,path,body=None:request(arm['url'],plan['credentials']['Owner']['token'],method,path,body)
administrative_put(base,api,'principals',{'operationId':'role-owner-r251:source-human','id':identity['principalId'],'name':'Regular QA release requester B','kind':'human','enrollmentCredential':identity['token']},method='POST')
administrative_put(base,api,'rooms/'+arm['room']+'/membership',{'operationId':'role-owner-r251:source-human-room','principalId':identity['principalId'],'can_read':True,'can_post':True,'can_request':True,'revision':0})
role=api('GET','agents/'+arm['agent']+'/role')
owner=plan['credentials']['Owner']['principalId']
assert role['decision_owner']==owner and identity['principalId']!=owner
assert api('GET','principals/'+identity['principalId'])['administrator'] is False
live=Store(json.loads(Path('/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json').read_text()))
try:
 with live.pool.connection() as c:
  column=c.execute("SELECT 1 FROM information_schema.columns WHERE table_name='hb_agent_role' AND column_name='decision_owner'").fetchone()
 assert column is None,'Unexpected live schema change: inspect, do not claim this task migrated it'
finally:live.close()
saved(base/'human-owner-readback.json',{'at':time.time(),'decisionOwnerA':owner,'sourceHumanB':identity['principalId'],'sourceHumanBAdministrator':False,'canonicalRole':role,'liveDecisionOwnerColumnAbsent':column is None,'modelsStarted':0})
print(json.dumps({'decisionOwnerA':owner,'sourceHumanB':identity['principalId'],'explicitBootstrapOwnerVerified':role['decision_owner']==owner,'liveSchemaUntouched':column is None,'modelsStarted':0}))
