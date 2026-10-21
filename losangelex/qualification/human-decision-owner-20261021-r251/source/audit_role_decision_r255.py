"""Independent actual-state, authenticated human history and native-owner output audit."""
import json,time,hashlib,runpy,subprocess,tempfile,os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector.host import request
from hollywood_backbone.store import digest as canonical_digest

ROOT=Path('/var/lib/lax-role-decision-owner-20261020-r251')
BASE=ROOT/'role-owner-r255';RUN=BASE/'run';P=ROOT/'protocol-r255'
Q=Path('/aosp/development/lax-three-context-20261018-r01/qualification')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pid(u):return subprocess.check_output(['systemctl','show',u,'-p','MainPID','--value'],text=True).strip()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'))
def wire(v):return json.loads(json.dumps(v,default=str))
def main():
 arm=json.loads((BASE/'public.json').read_text());peer=json.loads((BASE/'peer/public.json').read_text())
 owner=json.loads((BASE/'installation-intent.json').read_text())['credentials']['Owner']
 human_b=json.loads((BASE/'source-human.json').read_text())
 original_result=RUN/'result.json'
 observation=json.loads(original_result.read_text());result=observation
 waiting=json.loads((RUN/'role-question-waiting.json').read_text())
 retirement=json.loads((RUN/'retirement.json').read_text())
 intent=json.loads((RUN/'execution-intent.json').read_text());protocol=json.loads((P/'protocol.json').read_text())
 checks={};detail={}
 def mark(name,value):
  checks[name]=bool(value)
 def history(token,view):
  rows=[];cursor=0;pages=0
  while True:
   response=request(arm['url'],token,'GET','rooms/'+arm['room']+'/history?view='+view+'&limit=100&after='+str(cursor))
   pages+=1;rows+=response['events'];following=response['nextCursor']
   if not response['events'] or following==cursor:break
   assert following>cursor and pages<100
   cursor=following
  return rows,pages
 mark('frozen-protocol-files-unchanged',all(sha(P/n)==h for n,h in protocol['files'].items()) and sha(P/'protocol.json')==intent['protocolSha256'] and sha(Q/'run_role_decision_r255.py')==intent['runnerSha256'])
 db=psycopg.connect(**json.loads((ROOT/'database.json').read_text()),row_factory=dict_row)
 try:
  contexts=db.execute('SELECT agent,purpose,native_thread,active_turn FROM hb_purpose_context WHERE agent=ANY(%s::uuid[])',([arm['agent'],peer['agent']],)).fetchall()
  mark('same-six-histories-and-no-live-turns',len(contexts)==6 and all(c['active_turn'] is None and str(c['native_thread'])==result['histories'][str(c['agent'])+':'+c['purpose']] for c in contexts))
  deliveries=db.execute('SELECT * FROM hb_delivery WHERE authority=%s',(arm['authority'],)).fetchall()
  mark('all-own-deliveries-terminal',all(d['state'] in ['completed','cancelled','failed'] for d in deliveries))
  d=next(d for d in deliveries if str(d['id'])==result['roleDeliveryId'])
  waiting=json.loads((RUN/'role-question-waiting.json').read_text())
  mark('same-continued-work-claim-generation',d['state']=='completed' and str(d['claim_id'])==waiting['roleDelivery']['claim_id'] and d['generation']==waiting['roleDelivery']['generation'])
  attention=db.execute('SELECT * FROM hb_attention WHERE id=%s',(result['questionAttentionId'],)).fetchone()
  mark('configured-A-decision-authority-and-answer',str(attention['human'])==owner['principalId'] and str(attention['response_author'])==owner['principalId'] and owner['principalId']!=human_b['principalId'])
  events=db.execute('SELECT * FROM hb_event WHERE authority=%s ORDER BY seq',(arm['authority'],)).fetchall()
  role=next(e for e in events if e['id']==d['event']);fact=next(e for e in events if e['id']==role['source']);brequest=next(e for e in events if e['id']==fact['source'])
  mark('actual-peer-fact-traces-to-B-with-agent-authorship',str(brequest['author'])==human_b['principalId'] and str(fact['author'])==peer['agent'] and fact['kind']=='message' and fact['data'].get('nativeContext',{}).get('purpose')=='responder' and role['kind']=='control' and role['data'].get('type')=='roleWork')
  m=db.execute("SELECT * FROM hb_context_material WHERE agent=%s AND source=%s AND kind='work'",(arm['agent'],d['event'])).fetchone()
  captured=m['value']['roleInitiative']['roleSnapshot']
  mark('captured-role-owner-digest-bound',captured['decision_owner']==owner['principalId'] and canonical_digest(captured)==role['data']['roleSha256'] and captured['revision']==role['data']['roleRevision'])
  consumer_requests=[e for e in events if e['kind']=='request' and str(e['recipient'])==arm['agent']]
  initial_id=str(next(row for row in deliveries if str(row['id'])==result['initialDeliveryId'])['event'])
  mark('no-extra-assignment-besides-original-and-bound-answer',len(consumer_requests)==2 and {str(e['id']) for e in consumer_requests}=={initial_id,str(attention['response_event'])})
  answer_event=next(e for e in events if e['id']==attention['response_event'])
  mark('answer-exact-attention-and-original-work-scope',answer_event['source']==attention['event'] and answer_event['data']['attentionId']==str(attention['id']) and answer_event['data']['originalDeliveryId']==str(d['id']) and answer_event['audience']=='direct')
  consumer_work=db.execute("SELECT id,source,state FROM hb_context_material WHERE agent=%s AND kind='work'",(arm['agent'],)).fetchall()
  mark('no-replacement-work-from-answer',len(consumer_work)==2 and not any(x['source']==answer_event['id'] for x in consumer_work))
  answer_input=db.execute("SELECT value,state FROM hb_context_material WHERE agent=%s AND source=%s AND kind='input'",(arm['agent'],answer_event['id'])).fetchone()
  mark('answer-input-handled-on-same-work',answer_input is not None and answer_input['state']=='handled' and answer_input['value']['appliedToWorkId']==str(m['id']))
  for label in ['source-b-private-question-denied','source-b-answer-denied','agent-as-human-answer-denied']:
   mark(label,json.loads((RUN/(label+'.json')).read_text())['status']==403)
  answers=[e for e in events if e['data'].get('type')=='humanQuestionAnswer']
  mark('one-original-authenticated-answer',len(answers)==1 and str(answers[0]['author'])==owner['principalId'] and answers[0]['id']==attention['response_event'] and json.loads((RUN/'owner-a-answer-receipt.json').read_text())['postCount']==1)
  mark('answer-amends-same-work',any(u['sourceEventId']==str(answers[0]['id']) for u in m['value']['updates']))
  mark('writer-idle-before-authenticated-answer',all(c['active_turn'] is None for c in waiting['contexts'] if c['purpose']=='writer' and c['agent']==arm['agent']))
  canary='qa-owner-note-71f3'
  mark('room-events-body-and-data-exclude-private-canary',all(canary not in canonical(wire(e)) for e in events if e['audience']=='room'))
  feeds={};page_counts={}
  for label,token in [('A',owner['token']),('B',human_b['token'])]:
   for view in ['all','conversation','activity']:
    feeds[label+':'+view],page_counts[label+':'+view]=history(token,view)
  answer_id=str(attention['response_event']);question_id=str(attention['event'])
  mark('private-question-and-answer-visible-to-A',all(any(e['id']==i for e in feeds['A:all']) for i in [answer_id,question_id]))
  mark('B-all-projections-exclude-private-note-and-question-answer',all(canary not in canonical(e) and e['id'] not in [answer_id,question_id] for key,rows in feeds.items() if key.startswith('B:') for e in rows))
  mark('private-canary-is-real-not-vacuous',any(canary in canonical(e) for e in feeds['A:all']))
  final_id=str(d['result_event'])
  mark('completed-role-final-visible-to-both-humans',all(any(e['id']==final_id for e in feeds[label+':conversation']) for label in ['A','B']))
  actions=[e for e in feeds['B:activity'] if e['data'].get('deliveryId')==str(d['id']) and e['data'].get('phase')=='completed' and e['data'].get('nativeType')=='commandExecution']
  mark('real-attributed-native-commands-visible-as-activity',bool(actions) and all(e['data'].get('agentId')==arm['agent'] and e['data'].get('executionScope',{}).get('deliveryId')==str(d['id']) and e['data'].get('turn')==e['data'].get('executionScope',{}).get('nativeTurn') for e in actions))
  mark('new-writer-inference-after-answer-same-history',any(e['data']['turn']!=waiting['attention']['native_turn'] and __import__('datetime').datetime.fromisoformat(e['created_at'])>answers[0]['created_at'] for e in actions))
  detail.update(humanFeedPages=page_counts,questionEventId=question_id,answerEventId=answer_id,roleEventId=str(role['id']),roleDeliveryId=str(d['id']),peerFactEventId=str(fact['id']),nativeCommandActivityEventIds=[e['id'] for e in actions],workId=str(m['id']))
  scorer=runpy.run_path(str(P/'outcome.py'));work=Path(arm['workspace']);source=Path(peer['workspace'])/'catalog.json'
  req=json.loads((P/'RELEASE-REQUIREMENTS.json').read_text());actual_catalog=json.loads(source.read_text())
  mark('engineer-source-matches-new-frozen-release',canonical(req)==canonical(actual_catalog))
  mark('strict-delivered-bulletin-and-provenance',canonical(json.loads((work/'bulletin.json').read_text()))==canonical(scorer['expected'](req)) and json.loads((work/'bulletin-source.json').read_text())=={'hostId':arm['host'],'path':str(source),'sha256':sha(source)} and json.loads((work/'audience.json').read_text())=={'scope':'team-use','sourceSha256':sha(source)})
  mark('delivered-artifacts-exclude-private-canary',all(canary not in (work/n).read_text() for n in ['build_bulletin.py','bulletin.json','bulletin-source.json','audience.json']))
  cases=[req]+scorer['cases'](P);probes=[]
  with tempfile.TemporaryDirectory(prefix='role-owner-independent-',dir=work) as folder:
   os.chown(folder,arm['uid'],arm['gid']);f=Path(folder)/'catalog.json'
   for i,case in enumerate(cases):
    f.write_text(case if type(case) is str else json.dumps(case));os.chown(f,arm['uid'],arm['gid']);before=f.read_bytes()
    try:expected=scorer['expected'](json.loads(f.read_text()));valid=True
    except Exception:expected=None;valid=False
    run=subprocess.run(['setpriv','--reuid='+str(arm['uid']),'--regid='+str(arm['gid']),'--init-groups','--no-new-privs','/opt/lax-three-context-20261018-r01/venv-r251/bin/python',str(work/'build_bulletin.py'),str(f)],cwd=work,capture_output=True,text=True,timeout=15)
    try:got=json.loads(run.stdout)
    except Exception:got=None
    ok=(run.returncode==0 and canonical(got)==canonical(expected)) if valid else (run.returncode!=0 and 'PRIVATE-CANARY' not in run.stdout+run.stderr)
    probes.append({'case':i,'valid':valid,'exitCode':run.returncode,'passed':ok and f.read_bytes()==before})
  mark('delivered-cli-native-owner-strict-cases',all(v['passed'] for v in probes))
  detail['nativeOwnerProbes']=probes
  mark('requirements-preserved',sha(Path(peer['workspace'])/'RELEASE-REQUIREMENTS.json')==json.loads((BASE/'fixture-receipt.json').read_text())['files'][str(Path(peer['workspace'])/'RELEASE-REQUIREMENTS.json')])
  mark('all-eight-owned-services-retired',len(retirement['pids'])==8 and all(pid(u)=='0' for u in retirement['pids']))
  mark('protected-services-stay-unchanged',retirement['protectedPidsUnchanged'] and all(pid(u)==p for u,p in retirement['protectedPids'].items()))
  mark('only-own-placements-disabled',all(not row['enabled'] for row in db.execute('SELECT enabled FROM hb_placement WHERE authority=%s',(arm['authority'],)).fetchall()))
  report={'schema':'lax-role-human-independent-audit/v1','at':time.time(),'planSha256':sha(Q/'role-decision-independent-audit-plan-r255.json'),'runnerSha256':sha(__file__),'originalResultPath':str(original_result),'originalResultSha256':sha(original_result),'originalProtocolState':observation['state'],'relatedPriorAttempts':'r251 setup failure, r252 driver403 failure, r253 wrong assignment count retained; this is a fresh separate actual-model cohort.','checks':checks,'passed':all(checks.values()),'detail':detail,'scope':'Read-only audit plus native-owner disposable CLI probes on same frozen actual-model run, not a new model trial, no output repair or statistical reliability claim.'}
  (Q/'role-decision-independent-audit-r255.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps({'passed':report['passed'],'checks':checks,'failed':[n for n,v in checks.items() if not v]}))
  if not report['passed']:raise SystemExit(1)
 finally:db.close()
if __name__=='__main__':main()
