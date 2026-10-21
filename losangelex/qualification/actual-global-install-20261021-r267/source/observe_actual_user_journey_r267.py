import json,time,sys
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector.journal import saved
Q=Path('/var/lib/lax-existing-global-adoption-20261021-r266/cutover-r267/actual-user-journey')
p=json.loads((Q/'protocol.json').read_text());mode=sys.argv[1];assert mode in ['question','complete']
cfg=json.loads(Path('/etc/harness/production/database.json').read_text());db=psycopg.connect(**cfg,row_factory=dict_row,autocommit=True)
db.execute('SET default_transaction_read_only=on')
receipt=json.loads((Q/'request-receipt.json').read_text())['accepted'];event=receipt['event']['id']
start=time.time();deadline=min(json.loads((Q/'request-send-intent.json').read_text())['at']/1000+600,start+360);last=None
try:
 while time.time()<deadline:
  s={'at':time.time(),'mode':mode,
   'deliveries':db.execute('SELECT * FROM hb_delivery WHERE event=%s',(event,)).fetchall(),
   'contexts':db.execute('SELECT agent,purpose,native_thread,active_turn FROM hb_purpose_context WHERE agent=%s ORDER BY purpose',(p['agentId'],)).fetchall(),
   'materials':db.execute('SELECT * FROM hb_context_material WHERE agent=%s AND source=%s ORDER BY created_at',(p['agentId'],event)).fetchall(),
   'attention':db.execute("SELECT * FROM hb_attention WHERE room=%s ORDER BY created_at",(p['roomId'],)).fetchall(),
   'events':db.execute('SELECT * FROM hb_event WHERE room=%s ORDER BY seq',(p['roomId'],)).fetchall()}
  saved(Q/'latest.json',json.loads(json.dumps(s,default=str)))
  signature=([d['state'] for d in s['deliveries']],[(c['purpose'],bool(c['active_turn'])) for c in s['contexts']],[(a['method'],a['state']) for a in s['attention']])
  if signature!=last:
   print(json.dumps({'at':s['at'],'phase':mode,'state':signature}),flush=True);last=signature
  qs=[a for a in s['attention'] if a['state']=='pending' and a['method'] in ['hollywood/question','item/tool/requestUserInput']]
  if mode=='question' and qs:
   assert len(qs)==1
   saved(Q/'question-observed.json',json.loads(json.dumps(s,default=str)));print(json.dumps({'result':'question-pending','attentionId':str(qs[0]['id']),'request':qs[0]['request']}),flush=True);break
  if s['deliveries'] and all(d['state'] in ['completed','failed','cancelled','unknown'] for d in s['deliveries']):
   if mode=='question':raise RuntimeError('Original task settled before required question')
   if not all(d['state']=='completed' for d in s['deliveries']):raise RuntimeError('Original task did not complete successfully')
   if all(c['active_turn'] is None for c in s['contexts']):
    saved(Q/'complete-observed.json',json.loads(json.dumps(s,default=str)));print(json.dumps({'result':'original-completed','events':len(s['events'])}),flush=True);break
  time.sleep(2)
 else:raise TimeoutError('Original operation did not reach required phase within frozen window; inspect same turn, no resubmit')
finally:db.close()
