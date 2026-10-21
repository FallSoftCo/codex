"""Actual two-human native role question/answer journey; run once, no coaching/replay."""
import json,time,hashlib,subprocess,runpy,importlib.util
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector.host import request
from lax_connector.journal import saved
from lax_connector.purpose_install import activate
from lax_connector.collaboration_capture import administrative_put

ROOT=Path('/var/lib/lax-role-decision-owner-20261020-r251');BASE=ROOT/'role-owner-r252';P=BASE/'continuation-r253-protocol'
Q=Path('/aosp/development/lax-three-context-20261018-r01/qualification')
spec=importlib.util.spec_from_file_location('bounded_helpers',Q/'run_standing_r242.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
sha=h.digest;pid=h.pid;wire=h.wire
def save(p,v):saved(p,wire(v))
def main():
 arm=json.loads((BASE/'public.json').read_text());peer=json.loads((BASE/'peer/public.json').read_text())
 plan=json.loads((BASE/'installation-intent.json').read_text());person_b=json.loads((BASE/'source-human.json').read_text())
 owner=plan['credentials']['Owner'];configs=[json.loads(Path(x['config']).read_text()) for x in [arm,peer]]
 api=lambda method,path,body=None:request(arm['url'],owner['token'],method,path,body)
 bapi=lambda method,path,body=None:request(arm['url'],person_b['token'],method,path,body)
 protocol=json.loads((P/'protocol.json').read_text())
 for n,digest in protocol['files'].items():assert sha(P/n)==digest
 out=BASE/'continuation-r253';assert not out.exists(),'Inspect original receipts; never replay this journey'
 out.mkdir(mode=0o700);(out/'administration').mkdir(mode=0o700)
 protected=['hollywood-backbone.service','nextcomp-native-core.service','harness-postgres.service','hollywood-native-pilot-20261019-r01.service','lax-agent-483b0ac5-cccfd79ee934-reader.service','lax-agent-483b0ac5-cccfd79ee934-writer.service','lax-agent-483b0ac5-cccfd79ee934-responder.service']
 before={u:pid(u) for u in protected};units=[*arm['units'].values(),*peer['units'].values(),*arm['infrastructure']]
 save(out/'execution-intent.json',{'at':time.time(),'protocolSha256':sha(P/'protocol.json'),'runnerSha256':sha(__file__),'helperSha256':sha(Q/'run_standing_r242.py'),'packages':'SDK115/H81','model':'gpt-6.1-sol/xhigh','protectedPids':before,'participant':'Disclosed scripted human A and regular human B; actual peer/role models','noModelRemindersOrArtifactRepair':True})
 db=psycopg.connect(**json.loads((ROOT/'database.json').read_text()),row_factory=dict_row,autocommit=True)
 def snap():
  return {'deliveries':db.execute('SELECT * FROM hb_delivery WHERE authority=%s ORDER BY id',(arm['authority'],)).fetchall(),
   'contexts':db.execute('SELECT agent,purpose,native_thread,active_turn FROM hb_purpose_context WHERE agent=ANY(%s::uuid[]) ORDER BY agent,purpose',([arm['agent'],peer['agent']],)).fetchall(),
   'materials':db.execute("SELECT * FROM hb_context_material WHERE agent=ANY(%s::uuid[]) ORDER BY created_at",([arm['agent'],peer['agent']],)).fetchall(),
   'attention':db.execute('SELECT * FROM hb_attention WHERE authority=%s ORDER BY created_at',(arm['authority'],)).fetchall(),
   'events':db.execute("SELECT * FROM hb_event WHERE authority=%s AND data->>'type' IS DISTINCT FROM 'executionActivity' ORDER BY seq",(arm['authority'],)).fetchall()}
 def settled(s):
  return all(d['state'] in ['completed','cancelled','failed'] for d in s['deliveries']) and all(c['active_turn'] is None for c in s['contexts']) and not any(m['kind']=='input' and m['state']=='pending' or m['kind']=='need' and m['state']=='ready' for m in s['materials'])
 def post_once(label,call,path,body,lookup):
  assert not (out/(label+'-intent.json')).exists()
  save(out/(label+'-intent.json'),{'at':time.time(),'path':path,'body':body})
  try:r=call('POST',path,body)
  except Exception as e:
   save(out/(label+'-transport-gap.json'),{'error':type(e).__name__,'policy':'Read original receipt only; never replay POST'})
   r=call('GET',lookup)
  save(out/(label+'-receipt.json'),{'at':time.time(),'result':r,'postCount':1});return r
 def send(label,call,who,filename):
  op='role-owner-r253:'+label
  return post_once(label,call,'rooms/'+arm['room']+'/messages',{'operationId':op,'kind':'request','audience':'room','recipientId':who['agent'],'body':(P/filename).read_text()},'commands/'+op)
 def rejected(label,call,method,path,body=None):
  from lax_connector.errors import HttpFailure
  from urllib.error import HTTPError
  try:call(method,path,body)
  except (HttpFailure,HTTPError) as e:
   save(out/(label+'.json'),{'at':time.time(),'status':e.status,'error':str(e),'expectedStatus':403})
   assert e.status==403,(label,e.status)
   return
  raise AssertionError(label+' unexpectedly authorized')
 started=time.time();deadline=started+protocol['budgets']['seconds'];state='failed';error=None;original=None;answer=None;question=None;histories=None;phases=[]
 def check_usage():
  values=[h.usage(c) for c in configs]
  assert sum(v['tokens'] for v in values)<=protocol['budgets']['nativeTokens'],'Frozen native token ceiling'
  return values
 try:
  assert all(pid(u)=='0' for u in [*arm['units'].values(),*peer['units'].values()])
  pre=snap()
  original='4031930d-e05e-4b4c-b560-ba11f29846ac'
  oldrole='9724f2e8-f22f-53e3-be14-1ccac68019f8';oldattention='e7032450-26f6-5401-9a21-1af7bfb87443'
  histories={str(c['agent'])+':'+c['purpose']:c['native_thread'] for c in pre['contexts']}
  assert len(histories)==6 and not any(c['active_turn'] for c in pre['contexts'])
  save(out/'prior-state.json',pre)
  for who in [arm,peer]:
   row=api('GET','placements/'+who['agent'])
   assert row['placement']['enabled'] is False
   administrative_put(out,api,'placements/'+who['agent'],{'operationId':'role-owner-r253:enable:'+who['agent'],'hostId':who['host'],'revision':row['placement']['revision'],'enabled':True})
  # Explicit new QA activation; existing installer activation receipt is immutable.
  subprocess.run(['systemctl','start',*arm['infrastructure']],check=True,capture_output=True)
  subprocess.run(['systemctl','start',*arm['units'].values(),*peer['units'].values()],check=True,capture_output=True)
  limit=time.time()+60
  while True:
   s=snap()
   if len(s['contexts'])==6 and all(c['native_thread'] for c in s['contexts']):break
   assert time.time()<limit,'Native cohort startup incomplete';time.sleep(.5)
  limit=time.time()+45
  while True:
   s=snap();old=next(d for d in s['deliveries'] if str(d['id'])==oldrole)
   oldq=next(a for a in s['attention'] if str(a['id'])==oldattention)
   if old['state']=='cancelled' and oldq['state']=='expired':break
   assert time.time()<limit,'Prior known cancellation did not settle; never replay old work'
   time.sleep(1)
  assert oldq['response_event'] is None and oldq['response_author'] is None
  assert next(d for d in s['deliveries'] if str(d['id'])==original)['state']=='completed'
  assert all(c['native_thread']==histories[str(c['agent'])+':'+c['purpose']] for c in s['contexts'])
  w=Path(arm['workspace']);p=Path(peer['workspace']);scorer=runpy.run_path(str(P/'outcome.py'))
  save(out/'cancelled-original-preserved.json',s)
  phases.append('prior-completed-and-cancelled-work-preserved')
  peer_request=send('release-b',bapi,peer,'engineer-release.txt')
  phase_end=min(deadline,time.time()+protocol['budgets']['perPhaseSeconds']);next_usage=0
  while time.time()<phase_end:
   s=snap();save(out/'latest.json',{'at':time.time(),'phase':'await-native-role-question','snapshot':s})
   pending=[a for a in s['attention'] if str(a['agent'])==arm['agent'] and str(a['id'])!=oldattention and a['state']=='pending' and a['method'] in ['hollywood/question','item/tool/requestUserInput']]
   if pending:
    q=pending[0];d=next(d for d in s['deliveries'] if d['id']==q['delivery']);event=next(e for e in s['events'] if e['id']==d['event'])
    assert event['kind']=='control' and event['data'].get('type')=='roleWork','Question was not from role-origin work'
    fact=next(e for e in s['events'] if e['id']==event['source'])
    assert fact['kind']=='message' and str(fact['author'])==peer['agent'] and fact['data'].get('nativeContext',{}).get('purpose')=='responder','Initiative did not originate in the real peer report'
    human_source=next(e for e in s['events'] if e['id']==fact['source'])
    assert str(human_source['author'])==person_b['principalId'],'Peer report did not trace to source human B'

    assert str(q['human'])==owner['principalId'] and str(q['human'])!=person_b['principalId'],'Wrong human decision authority'
    # Wait for the original writer inference to finish; prove event-backed
    # continuation rather than native synchronous answer/steer.
    writer=next(c for c in s['contexts'] if str(c['agent'])==arm['agent'] and c['purpose']=='writer')
    if writer['active_turn'] is None:
     question=q;role_delivery=d;save(out/'role-question-waiting.json',{'at':time.time(),'attention':q,'roleDelivery':d,'roleOrigin':event,'contexts':s['contexts']});break
   if time.time()>=next_usage:check_usage();next_usage=time.time()+15
   time.sleep(2)
  else:raise RuntimeError('Native role question/idle writer boundary did not occur within frozen window')
  aid=str(question['id']);receipt=api('GET','attention/'+aid);assert receipt['canRespond']
  answers={q['id']:{'answers':[(P/'owner-answer.txt').read_text()]} for q in receipt['attention']['request']['questions']}
  body={'operationId':'role-owner-r253:answer-b-negative','scope':receipt['scope'],'response':{'answers':answers}}
  rejected('source-b-private-question-denied',bapi,'GET','attention/'+aid)
  count_before=db.execute('SELECT count(*) AS n FROM hb_delivery WHERE authority=%s',(arm['authority'],)).fetchone()['n']
  rejected('source-b-answer-denied',bapi,'POST','attention/'+aid+'/response',body)
  # A native agent credential cannot stand in for a human even if administrator.
  agent_api=lambda method,path,body=None:request(arm['url'],configs[0]['tokens']['writer'],method,path,body)
  rejected('agent-as-human-answer-denied',agent_api,'POST','attention/'+aid+'/response',{**body,'operationId':'role-owner-r253:agent-answer-negative'})
  assert db.execute('SELECT count(*) AS n FROM hb_delivery WHERE authority=%s',(arm['authority'],)).fetchone()['n']==count_before
  body['operationId']='role-owner-r253:answer-a'
  assert len(json.dumps(body).encode())<6000
  answer=post_once('owner-a-answer',api,'attention/'+aid+'/response',body,'attention/'+aid+'/commands/'+body['operationId'])
  phases += ['role-question-targets-a-not-evidence-b','b-and-agent-rejected','one-authenticated-a-answer']
  end=min(deadline,time.time()+protocol['budgets']['perPhaseSeconds']);quiet=None;next_usage=0
  while time.time()<end:
   s=snap();save(out/'latest.json',{'at':time.time(),'phase':'continue-original-role-work','snapshot':s})
   if settled(s):
    quiet=quiet or time.time()
    if time.time()-quiet>=protocol['budgets']['quietSeconds']:break
   else:quiet=None
   if time.time()>=next_usage:check_usage();next_usage=time.time()+15
   time.sleep(2)
  else:raise RuntimeError('Original role work did not settle after its answer within frozen window')
  role_final=next(d for d in s['deliveries'] if d['id']==role_delivery['id'])
  assert role_final['state']=='completed' and role_final['generation']==role_delivery['generation'] and role_final['claim_id']==role_delivery['claim_id']
  role_works=[m for m in s['materials'] if str(m['agent'])==arm['agent'] and m['kind']=='work' and m['value'].get('roleInitiative')]
  new_works=[m for m in role_works if m['source']==role_delivery['event']]
  assert len(role_works)==2 and len(new_works)==1 and new_works[0]['state']=='complete'
  assert next(d for d in s['deliveries'] if str(d['id'])==oldrole)['state']=='cancelled'
  oq=next(a for a in s['attention'] if str(a['id'])==oldattention)
  assert oq['state']=='expired' and oq['response_event'] is None
  assert sum(str(e['recipient'])==arm['agent'] and e['kind']=='request' for e in s['events'])==1
  expected=scorer['expected'](json.loads((p/'catalog.json').read_text()));got=json.loads((w/'bulletin.json').read_text())
  assert json.dumps(got,sort_keys=True)==json.dumps(expected,sort_keys=True)
  actual_source=sha(p/'catalog.json');provenance=json.loads((w/'bulletin-source.json').read_text())
  assert provenance=={'hostId':arm['host'],'path':str(p/'catalog.json'),'sha256':actual_source}
  assert json.loads((w/'audience.json').read_text())=={'scope':'team-use','sourceSha256':actual_source}
  probe=scorer['probe'](w/'build_bulletin.py',scorer['cases'](P));assert all(x['passed'] for x in probe)
  canary='qa-owner-note-71f3'
  assert not any(canary in e['body'] for e in s['events'] if e['audience']=='room')
  for name in ['build_bulletin.py','bulletin.json','bulletin-source.json','audience.json']:assert canary not in (w/name).read_text()
  follow=next(m for m in s['materials'] if m['id']==new_works[0]['id'])
  question_answers=[e for e in s['events'] if e['data'].get('type')=='humanQuestionAnswer']
  assert len(question_answers)==1 and str(question_answers[0]['author'])==owner['principalId']
  assert any(u['sourceEventId']==str(question_answers[0]['id']) for u in follow['value']['updates'])
  assert all(c['native_thread']==histories[str(c['agent'])+':'+c['purpose']] for c in s['contexts'])
  assert next(d for d in s['deliveries'] if str(d['id'])==original)['state']=='completed'
  state='bounded-native-role-human-continuation-passed'
  save(out/'result.json',{'at':time.time(),'state':state,'phases':phases,'snapshot':s,'histories':histories,'usage':check_usage(),'roleDeliveryId':str(role_delivery['id']),'initialDeliveryId':original,'questionAttentionId':aid,'answerReceipt':answer,'strictUnseenAndInvalid':probe,'seconds':time.time()-started,'actualSource':{'hostId':arm['host'],'path':str(p/'catalog.json'),'sha256':actual_source},'expectedOutput':expected,'actualOutput':got,'scope':'Continued six histories after disclosed driver failure; one explicit two-human decision-required actual2agent/6context journey; not broad question relevance, scale or production readiness.'})
 except BaseException as e:
  error=type(e).__name__+': '+str(e);save(out/'failure.json',{'at':time.time(),'error':error,'state':state,'phases':phases,'snapshot':snap(),'noOriginalTaskReplay':True})
 finally:
  s=snap()
  for d in s['deliveries']:
   if d['state'] not in ['completed','cancelled','failed','unknown']:
    label='retire-'+str(d['id']);save(out/(label+'-intent.json'),{'at':time.time(),'action':'cancel only owned qualification delivery','id':str(d['id'])})
    try:save(out/(label+'-receipt.json'),api('POST','deliveries/'+str(d['id'])+'/cancel',{}))
    except Exception as e:save(out/(label+'-gap.json'),{'error':type(e).__name__,'noReplay':True})
  limit=time.time()+25
  while time.time()<limit and any(c['active_turn'] for c in snap()['contexts']):time.sleep(1)
  pre=snap();subprocess.run(['systemctl','stop',*units],check=True,capture_output=True)
  for who in [arm,peer]:
   row=api('GET','placements/'+who['agent'])
   administrative_put(out,api,'placements/'+who['agent'],{'operationId':'role-owner-r253:retire:'+who['agent'],'hostId':who['host'],'revision':row['placement']['revision'],'enabled':False})
  save(out/'retirement.json',{'at':time.time(),'state':state,'error':error,'pids':{u:pid(u) for u in units},'preStopContexts':pre['contexts'],'protectedPids':{u:pid(u) for u in protected},'protectedPidsUnchanged':{u:pid(u) for u in protected}==before,'originalsRetained':True})
  db.close()
 print(json.dumps({'state':state,'error':error,'phases':phases,'ownUnitsStopped':all(pid(u)=='0' for u in units)}),flush=True)
 if error:raise SystemExit(1)
if __name__=='__main__':main()
