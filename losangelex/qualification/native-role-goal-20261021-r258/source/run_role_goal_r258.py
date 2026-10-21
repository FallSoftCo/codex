"""Actual two-human native role question/answer journey; run once, no coaching/replay."""
import json,time,hashlib,subprocess,runpy,importlib.util
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector.host import request
from lax_connector.journal import saved
from lax_connector.purpose_install import activate
from lax_connector.collaboration_capture import administrative_put

ROOT=Path('/var/lib/lax-role-goal-20261021-r258');BASE=ROOT/'role-goal-r258';P=ROOT/'protocol'
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
 out=BASE/'run';assert not out.exists(),'Inspect original receipts; never replay this journey'
 out.mkdir(mode=0o700);(out/'administration').mkdir(mode=0o700)
 protected=['hollywood-backbone.service','nextcomp-native-core.service','harness-postgres.service','hollywood-native-pilot-20261019-r01.service','lax-agent-483b0ac5-cccfd79ee934-reader.service','lax-agent-483b0ac5-cccfd79ee934-writer.service','lax-agent-483b0ac5-cccfd79ee934-responder.service']
 before={u:pid(u) for u in protected};units=[*arm['units'].values(),*peer['units'].values(),*arm['infrastructure']]
 save(out/'execution-intent.json',{'at':time.time(),'protocolSha256':sha(P/'protocol.json'),'runnerSha256':sha(__file__),'helperSha256':sha(Q/'run_standing_r242.py'),'packages':'SDK116/H81','model':'gpt-6.1-sol/xhigh','protectedPids':before,'participant':'Disclosed scripted human A and regular human B; actual peer/role models','noModelRemindersOrArtifactRepair':True})
 db=psycopg.connect(**json.loads((ROOT/'database.json').read_text()),row_factory=dict_row,autocommit=True)
 def snap():
  return {'goals':db.execute('SELECT * FROM hb_goal WHERE authority=%s ORDER BY id',(arm['authority'],)).fetchall(),
   'canonicalWork':db.execute('SELECT * FROM hb_work WHERE authority=%s ORDER BY id',(arm['authority'],)).fetchall(),
   'rooms':db.execute('SELECT id,name,purpose,owner FROM hb_room WHERE authority=%s ORDER BY id',(arm['authority'],)).fetchall(),
   'deliveries':db.execute('SELECT * FROM hb_delivery WHERE authority=%s ORDER BY id',(arm['authority'],)).fetchall(),
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
  op='role-goal-r258:'+label
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
  for who in [arm,peer]:activate(who['authority'],who['agent'])
  limit=time.time()+60
  while True:
   s=snap()
   if len(s['contexts'])==6 and all(c['native_thread'] for c in s['contexts']):break
   assert time.time()<limit,'Native cohort startup incomplete';time.sleep(.5)
  histories={str(c['agent'])+':'+c['purpose']:c['native_thread'] for c in s['contexts']}
  initial=send('initial-a',api,arm,'initial.txt');original=initial['deliveries'][0]['id'];phase_end=min(deadline,time.time()+protocol['budgets']['perPhaseSeconds']);quiet=None
  while time.time()<phase_end:
   s=snap();save(out/'latest.json',{'at':time.time(),'phase':'initial','snapshot':s})
   if settled(s):
    quiet=quiet or time.time()
    if time.time()-quiet>=protocol['budgets']['quietSeconds']:break
   else:quiet=None
   check_usage();time.sleep(3)
  else:raise RuntimeError('Initial finite task did not settle within frozen phase window')
  initial_row=next(d for d in s['deliveries'] if str(d['id'])==original)
  assert initial_row['state']=='completed'
  w=Path(arm['workspace']);p=Path(peer['workspace']);scorer=runpy.run_path(str(P/'outcome.py'))
  assert not s['goals'],'Initial setup created a premature perpetual Goal'
  assert not (w/'definition-proposal.json').exists()
  phases.append('initial-complete-before-later-release');save(out/'initial-complete.json',s)
  peer_request=send('release-b',bapi,peer,'engineer-release.txt')
  phase_end=min(deadline,time.time()+protocol['budgets']['perPhaseSeconds']);next_usage=0
  while time.time()<phase_end:
   s=snap();save(out/'latest.json',{'at':time.time(),'phase':'await-native-role-question','snapshot':s})
   pending=[a for a in s['attention'] if str(a['agent'])==arm['agent'] and a['state']=='pending' and a['method'] in ['hollywood/question','item/tool/requestUserInput']]
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
  proposal=Path(arm['workspace'])/'definition-proposal.json'
  raw_proposal=proposal.read_bytes();proposal_hash=sha(proposal)
  definition=json.loads(raw_proposal)
  assert type(definition) is dict and set(definition)=={'schema','objective','audienceOptions','acceptance','source'}
  assert type(definition['schema']) is int and definition['schema']==1
  assert isinstance(definition['objective'],str) and definition['objective'].strip()
  assert definition['audienceOptions']==['internal-operators','buyers']
  assert isinstance(definition['acceptance'],list) and definition['acceptance'] and all(isinstance(x,str) and x.strip() for x in definition['acceptance'])
  actual_source=Path(peer['workspace'])/'catalog.json'
  assert definition['source']=={'hostId':arm['host'],'path':str(actual_source),'sha256':sha(actual_source)}
  assert proposal_hash in __import__('json').dumps(question['request']),'Question did not present exact proposal digest'
  (out/'reviewed-proposal.json').write_bytes(raw_proposal)
  save(out/'reviewed-proposal-receipt.json',{'at':time.time(),'sha256':proposal_hash,'path':str(proposal),'source':definition['source'],'mode':'Scripted QA human checks frozen proposal shape and actual source before answering; no model coaching or expected output supplied'})
  aid=str(question['id']);receipt=api('GET','attention/'+aid);assert receipt['canRespond']
  answers={q['id']:{'answers':['Reviewed definition-proposal.json SHA256 '+proposal_hash+'. '+(P/'owner-answer.txt').read_text()]} for q in receipt['attention']['request']['questions']}
  body={'operationId':'role-goal-r258:answer-b-negative','scope':receipt['scope'],'response':{'answers':answers}}
  rejected('source-b-private-question-denied',bapi,'GET','attention/'+aid)
  count_before=db.execute('SELECT count(*) AS n FROM hb_delivery WHERE authority=%s',(arm['authority'],)).fetchone()['n']
  rejected('source-b-answer-denied',bapi,'POST','attention/'+aid+'/response',body)
  # A native agent credential cannot stand in for a human even if administrator.
  agent_api=lambda method,path,body=None:request(arm['url'],configs[0]['tokens']['writer'],method,path,body)
  rejected('agent-as-human-answer-denied',agent_api,'POST','attention/'+aid+'/response',{**body,'operationId':'role-goal-r258:agent-answer-negative'})
  assert db.execute('SELECT count(*) AS n FROM hb_delivery WHERE authority=%s',(arm['authority'],)).fetchone()['n']==count_before
  body['operationId']='role-goal-r258:answer-a'
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
  assert len(role_works)==1 and role_works[0]['state']=='complete'
  assert len(s['goals'])==1 and s['goals'][0]['state']=='accepted','Canonical Goal not accepted'
  goal=s['goals'][0];assert str(goal['owner'])==arm['agent'] and str(goal['room'])!=arm['room']
  goal_source=next(e for e in s['events'] if e['id']==goal['source'])
  assert goal_source['data'].get('type')=='goalOrigin' and goal_source['source']==role_delivery['event']
  assert str(goal_source['data']['originRequestId'])==str(role_delivery['event'])
  assert str(goal_source['room'])==str(goal['room'])
  assert proposal_hash in goal['acceptance'] and 'internal-operators' in goal['acceptance']
  assert s['canonicalWork'] and all(row['state']=='accepted' and row['goal']==goal['id'] for row in s['canonicalWork'])
  delivered_index=json.loads((w/'readiness-index.json').read_text())
  canonical_work=next(row for row in s['canonicalWork'] if str(row['id'])==delivered_index['workId'])
  assert str(canonical_work['owner'])==peer['agent']
  assert proposal_hash in canonical_work['acceptance'] and 'internal-operators' in canonical_work['acceptance']
  peer_delivery=next(d for d in s['deliveries'] if d['id']==canonical_work['delivery'])
  assert peer_delivery['state']=='completed' and peer_delivery['result_event']
  assert canonical_work['report_event'] and canonical_work['evidence']
  evidence=next(e for e in canonical_work['evidence'] if e['relativePath']=='readiness.json')
  assert evidence['hostId']==arm['host'] and evidence['sha256']==sha(p/'readiness.json') and evidence['size']==(p/'readiness.json').stat().st_size
  expected=scorer['packet']((p/'catalog.json').read_bytes(),'internal-operators');got=json.loads((p/'readiness.json').read_text())
  assert scorer['valid_packet']((p/'catalog.json').read_bytes(),got,'internal-operators')
  assert json.loads((w/'readiness-index.json').read_text())=={'goalId':str(goal['id']),'workId':str(canonical_work['id']),'definitionSha256':proposal_hash,'packet':evidence}
  assert sha(proposal)==proposal_hash,'Approved proposal bytes changed'
  actual_source=sha(p/'catalog.json')
  definition_proof={'goalId':str(goal['id']),'workId':str(canonical_work['id']),'reviewedProposalSha256':proposal_hash,'canonicalEvidence':evidence,'binding':'Observed existing prose references and independently verified immutable artifact bytes, not typed server-enforced definition binding'}
  follow=next(m for m in role_works if m['source']==role_delivery['event'])
  assert follow['value']['goalPrerequisites']==[str(goal['id'])]
  assert any(g['goalId']==str(goal['id']) and g['state']=='accepted' for g in follow['value']['goalResults'])
  rejected('source-b-new-room-read-denied',bapi,'GET','rooms/'+str(goal['room'])+'/history?view=all')
  canary='qa-goal-owner-note-258'
  assert not any(canary in e['body'] for e in s['events'] if e['audience']=='room')
  for path in [w/'definition-proposal.json',w/'readiness-index.json',p/'readiness.json']:assert canary not in path.read_text()
  follow=next(m for m in s['materials'] if m['id']==role_works[0]['id'])
  question_answers=[e for e in s['events'] if e['data'].get('type')=='humanQuestionAnswer']
  assert len(question_answers)==1 and str(question_answers[0]['author'])==owner['principalId']
  answer_event=question_answers[0]
  assert str(answer_event['id'])==api('GET','attention/'+aid)['attention']['response_event']
  assert str(answer_event['source'])==str(question['event']) and answer_event['data']['originalDeliveryId']==str(role_delivery['id'])
  consumer_requests=[e for e in s['events'] if str(e['recipient'])==arm['agent'] and e['kind']=='request']
  human_requests=[e for e in consumer_requests if str(e['author']) in [owner['principalId'],person_b['principalId']]]
  assert {str(e['id']) for e in human_requests}=={str(initial_row['event']),str(answer_event['id'])}
  for event in consumer_requests:
   if event not in human_requests:assert event['data'].get('goalReview') is True and str(event['data']['goalId'])==str(goal['id'])
  consumer_work=[m for m in s['materials'] if str(m['agent'])==arm['agent'] and m['kind']=='work']
  assert not any(m['source']==answer_event['id'] for m in consumer_work)
  assert all(m['source']==role_delivery['event'] or m['source']==initial_row['event'] or next(e for e in s['events'] if e['id']==m['source'])['data'].get('goalReview') is True for m in consumer_work)
  answer_input=next(m for m in s['materials'] if m['kind']=='input' and m['source']==answer_event['id'])
  assert answer_input['state']=='handled' and answer_input['value']['appliedToWorkId']==str(follow['id'])
  assert any(u['sourceEventId']==str(question_answers[0]['id']) for u in follow['value']['updates'])
  assert all(c['native_thread']==histories[str(c['agent'])+':'+c['purpose']] for c in s['contexts'])
  assert next(d for d in s['deliveries'] if str(d['id'])==original)['state']=='completed'
  state='bounded-native-role-goal-peer-delivery-passed'
  save(out/'result.json',{'at':time.time(),'state':state,'phases':phases,'snapshot':s,'histories':histories,'usage':check_usage(),'roleDeliveryId':str(role_delivery['id']),'initialDeliveryId':original,'questionAttentionId':aid,'answerReceipt':answer,'nativeGoalEvidence':definition_proof,'seconds':time.time()-started,'actualSource':{'hostId':arm['host'],'path':str(p/'catalog.json'),'sha256':actual_source},'expectedOutput':expected,'actualOutput':got,'scope':'One explicit role-origin native Goal/two-room/real peer Work journey; no natural goal-development, scale, statistical superiority or production claim.'})
 except BaseException as e:
  error=type(e).__name__+': '+str(e);save(out/'failure.json',{'at':time.time(),'error':error,'state':state,'phases':phases,'snapshot':snap(),'noOriginalTaskReplay':True,'traceback':__import__('traceback').format_exc()})
 finally:
  s=snap()
  for g in s['goals']:
   if g['state'] not in ['accepted','cancelled']:
    try:post_once('retire-goal-'+str(g['id']),api,'goals/'+str(g['id'])+'/state',{'operationId':'role-goal-r258:retire-goal:'+str(g['id']),'revision':g['revision'],'state':'cancelled','note':'Owned finite qualification ended; preserve original effects and receipts'},'commands/role-goal-r258:retire-goal:'+str(g['id']))
    except Exception as e:save(out/('retire-goal-'+str(g['id'])+'-gap.json'),{'error':type(e).__name__,'noReplay':True})
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
   administrative_put(out,api,'placements/'+who['agent'],{'operationId':'role-goal-r258:retire:'+who['agent'],'hostId':who['host'],'revision':row['placement']['revision'],'enabled':False})
  save(out/'retirement.json',{'at':time.time(),'state':state,'error':error,'pids':{u:pid(u) for u in units},'preStopContexts':pre['contexts'],'protectedPids':{u:pid(u) for u in protected},'protectedPidsUnchanged':{u:pid(u) for u in protected}==before,'originalsRetained':True})
  db.close()
 print(json.dumps({'state':state,'error':error,'phases':phases,'ownUnitsStopped':all(pid(u)=='0' for u in units)}),flush=True)
 if error:raise SystemExit(1)
if __name__=='__main__':main()
