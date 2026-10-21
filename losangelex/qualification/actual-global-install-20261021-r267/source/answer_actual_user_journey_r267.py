import json,time
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector.host import request
from lax_connector.journal import saved
Q=Path('/var/lib/lax-existing-global-adoption-20261021-r266/cutover-r267/actual-user-journey');p=json.loads((Q/'protocol.json').read_text());admin=json.loads((Q.parent.parent/'administrator.json').read_text());api=lambda m,r,b=None:request(admin['hollywoodUrl'],admin['token'],m,r,b)
assert not (Q/'answer.json').exists()
q=json.loads((Q/'question-observed.json').read_text());attention=next(a for a in q['attention'] if a['state']=='pending')
assert attention['human']==p['humanId'] and attention['agent']==p['agentId'] and attention['delivery']=='0c417797-66ff-49ae-aecf-7a497d984f44'
live=api('GET','attention/'+attention['id']);assert live['canRespond'] and live['attention']['state']=='pending'
question=live['attention']['request']['questions'];assert len(question)==1 and question[0]['id']=='report_filename'
assert [o['label'] for o in question[0]['options']]==['native-install-readiness.json','native-install-report.json']
db=psycopg.connect(**json.loads(Path('/etc/harness/production/database.json').read_text()),row_factory=dict_row,autocommit=True);db.execute('SET default_transaction_read_only=on');end=time.time()+65
while True:
 c=db.execute("SELECT * FROM hb_purpose_context WHERE agent=%s AND purpose='writer'",(p['agentId'],)).fetchone()
 if c['active_turn'] is None:break
 assert time.time()<end,'Original writer still active; do not force interrupt'
 time.sleep(1)
db.close()
saved(Q/'question-waiting-idle-boundary.json',{'at':time.time(),'attentionId':attention['id'],'originalDelivery':attention['delivery'],'writerIdle':True,'newHumanRequests':0})
saved(Q/'answer.json',{'path':'attention/'+attention['id']+'/response','lookup':'attention/'+attention['id']+'/commands/actual-native-r267:filename-answer','body':{'operationId':'actual-native-r267:filename-answer','scope':live['scope'],'response':{'answers':{'report_filename':{'answers':['native-install-readiness.json']}}}}})
print(json.dumps({'answerPrepared':True,'writerEndedOriginalInference':True,'originalAttentionId':attention['id'],'answer':'native-install-readiness.json','actualAnswerPosts':0}))
