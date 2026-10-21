"""Independent read-only native role/Goal/team audit; no model inputs or repair."""
import json,hashlib,time,subprocess
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector.host import request
ROOT=Path('/var/lib/lax-role-goal-20261021-r258');BASE=ROOT/'role-goal-r258';RUN=BASE/'run'
Q=Path('/aosp/development/lax-three-context-20261018-r01/qualification')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def wire(v):return json.loads(json.dumps(v,default=str))
def main():
 a=json.loads((BASE/'public.json').read_text());peer=json.loads((BASE/'peer/public.json').read_text())
 owner=json.loads((BASE/'installation-intent.json').read_text())['credentials']['Owner'];b=json.loads((BASE/'source-human.json').read_text())
 result=json.loads((RUN/'result.json').read_text());retire=json.loads((RUN/'retirement.json').read_text());intent=json.loads((RUN/'execution-intent.json').read_text())
 checks={};detail={}
 def mark(name,v):checks[name]=bool(v)
 def history(room,view):
  rows=[];cursor=0
  for _ in range(100):
   r=request(a['url'],owner['token'],'GET','rooms/'+room+'/history?after='+str(cursor)+'&limit=100&view='+view);rows+=r['events'];n=r['nextCursor']
   if not r['events'] or n==cursor:return rows
   assert n>cursor;cursor=n
  raise AssertionError('Bounded pagination exhausted')
 with psycopg.connect(**json.loads((ROOT/'database.json').read_text()),row_factory=dict_row) as c:
  mark('frozen-runner-and-protocol-unchanged',sha(Q/'run_role_goal_r258.py')==intent['runnerSha256'] and sha(ROOT/'protocol/protocol.json')==intent['protocolSha256'])
  contexts=c.execute('SELECT agent,purpose,native_thread,active_turn FROM hb_purpose_context WHERE agent=ANY(%s::uuid[])',([a['agent'],peer['agent']],)).fetchall()
  mark('same-six-histories-no-active-turns',len(contexts)==6 and all(x['active_turn'] is None and x['native_thread']==result['histories'][str(x['agent'])+':'+x['purpose']] for x in contexts))
  roles=c.execute('SELECT principal,home_room FROM hb_agent_role WHERE principal=ANY(%s::uuid[])',([a['agent'],peer['agent']],)).fetchall()
  mark('room-joins-do-not-move-role-home-or-agent-identity',len(roles)==2 and all(str(x['home_room'])==a['room'] for x in roles))
  systems=c.execute('SELECT agent,workspace FROM hb_context_system WHERE agent=ANY(%s::uuid[])',([a['agent'],peer['agent']],)).fetchall()
  configs={x['agent']:json.loads(Path(x['config']).read_text()) for x in [a,peer]}
  mark('private-context-workspaces-preserved',len(systems)==2 and all(str(x['workspace'])==configs[str(x['agent'])]['workspaceId'] for x in systems))
  deliveries=c.execute('SELECT * FROM hb_delivery WHERE authority=%s',(a['authority'],)).fetchall()
  events=c.execute('SELECT * FROM hb_event WHERE authority=%s ORDER BY seq',(a['authority'],)).fetchall()
  role=next(d for d in deliveries if str(d['id'])==result['roleDeliveryId'])
  origin=next(e for e in events if e['id']==role['event']);fact=next(e for e in events if e['id']==origin['source']);brequest=next(e for e in events if e['id']==fact['source'])
  mark('one-real-peer-report-to-native-role-initiative',origin['kind']=='control' and origin['data'].get('type')=='roleWork' and str(fact['author'])==peer['agent'] and fact['kind']=='message' and str(brequest['author'])==b['principalId'] and sum(e['data'].get('type')=='roleWork' for e in events)==1)
  initial=next(d for d in deliveries if str(d['id'])==result['initialDeliveryId']);initial_final=next(e for e in events if e['id']==initial['result_event'])
  mark('finite-setup-completed-before-release',initial['state']=='completed' and initial_final['seq']<brequest['seq'])
  attention=c.execute('SELECT * FROM hb_attention WHERE id=%s',(result['questionAttentionId'],)).fetchone()
  answer=next(e for e in events if e['id']==attention['response_event']);review=json.loads((RUN/'reviewed-proposal-receipt.json').read_text());proposal=Path(a['workspace'])/'definition-proposal.json'
  mark('one-explicit-owner-answer-to-exact-proposal',str(attention['human'])==owner['principalId'] and str(answer['author'])==owner['principalId'] and review['sha256'] in answer['body'] and sha(proposal)==review['sha256'] and sum(e['data'].get('type')=='humanQuestionAnswer' for e in events)==1)
  goal=c.execute('SELECT * FROM hb_goal WHERE id=%s',(result['nativeGoalEvidence']['goalId'],)).fetchone()
  goal_source=next(e for e in events if e['id']==goal['source'])
  mark('native-goal-cross-room-origin-preserved',goal['state']=='accepted' and str(goal['owner'])==a['agent'] and str(goal['room'])!=a['room'] and goal_source['data'].get('type')=='goalOrigin' and goal_source['source']==origin['id'] and str(goal_source['data']['originRequestId'])==str(origin['id']))
  work=c.execute('SELECT * FROM hb_work WHERE id=%s',(result['nativeGoalEvidence']['workId'],)).fetchone();assigned=next(e for e in events if e['id']==work['request_event'])
  mark('peer-implementation-after-human-review',work['state']=='accepted' and str(work['owner'])==peer['agent'] and assigned['seq']>answer['seq'] and assigned['room']==goal['room'])
  packet=json.loads((Path(peer['workspace'])/'readiness.json').read_text());catalog=Path(peer['workspace'])/'catalog.json';raw=catalog.read_bytes();features=json.loads(raw)['features']
  expected={'schema':1,'audience':'internal-operators','sourceSha256':sha(catalog),'features':sorted([{k:f[k] for k in ['id','version','title']} for f in features if f['state']=='released'],key=lambda x:x['id'])}
  mark('strict-correct-actual-packet',json.dumps(packet,sort_keys=True)==json.dumps(expected,sort_keys=True))
  evidence=next(e for e in work['evidence'] if e['relativePath']=='readiness.json')
  mark('canonical-report-hashes-actual-native-artifact',evidence['sha256']==sha(Path(peer['workspace'])/'readiness.json') and evidence['size']==(Path(peer['workspace'])/'readiness.json').stat().st_size and evidence['hostId']==a['host'])
  mark('reviewed-definition-referenced-in-goal-and-work',review['sha256'] in goal['acceptance'] and review['sha256'] in work['acceptance'])
  peer_delivery=next(d for d in deliveries if d['id']==work['delivery']);peer_final=next(e for e in events if e['id']==peer_delivery['result_event']);report=next(e for e in events if e['id']==work['report_event'])
  accepted_reviews=[e for e in events if e['data'].get('workflowAction')=='work.review' and e['data'].get('workId')==str(work['id']) and e['data'].get('workReview',{}).get('decision')=='accepted']
  mark('real-peer-report-before-completion-independent-global-review',str(report['author'])==peer['agent'] and report['seq']<peer_final['seq'] and len(accepted_reviews)==1 and str(accepted_reviews[0]['author'])==a['agent'] and accepted_reviews[0]['seq']>peer_final['seq'])
  goal_accepts=[e for e in events if e['data'].get('workflowAction')=='goal.state' and e['data'].get('goalId')==str(goal['id']) and e['data']['workflowReceipt']['state']=='accepted']
  mark('goal-acceptance-after-work-review',len(goal_accepts)==1 and goal_accepts[0]['seq']>accepted_reviews[0]['seq'])
  m=c.execute("SELECT * FROM hb_context_material WHERE source=%s AND agent=%s AND kind='work'",(origin['id'],a['agent'])).fetchone()
  role_final=next(e for e in events if e['id']==role['result_event'])
  mark('parent-role-completes-after-canonical-goal',role['state']=='completed' and m['state']=='complete' and role_final['seq']>goal_accepts[0]['seq'] and str(goal['id']) in m['value'].get('goalPrerequisites',[]) and any(x['goalId']==str(goal['id']) and x['state']=='accepted' for x in m['value'].get('goalResults',[])))
  index=json.loads((Path(a['workspace'])/'readiness-index.json').read_text())
  mark('index-names-actual-accepted-evidence',index=={'goalId':str(goal['id']),'workId':str(work['id']),'definitionSha256':review['sha256'],'packet':evidence})
  canary='qa-goal-owner-note-258'
  mark('no-private-note-in-any-room-event-body-or-data',all(canary not in json.dumps(wire(e)) for e in events if e['audience']=='room'))
  mark('private-answer-not-in-shared-goal-or-work-record',canary not in json.dumps(wire(goal)) and canary not in json.dumps(wire(work)))
  feeds={room:history(room,'all') for room in [a['room'],str(goal['room'])]}
  mark('A-sees-original-answer-and-final',any(e['id']==str(answer['id']) for e in feeds[a['room']]) and any(e['id']==str(role['result_event']) for e in feeds[a['room']]))
  from urllib.error import HTTPError
  try:request(a['url'],b['token'],'GET','rooms/'+str(goal['room'])+'/history')
  except HTTPError as ex:mark('B-without-membership-new-room-denied',ex.code==403)
  else:mark('B-without-membership-new-room-denied',False)
  actions=[e for room in feeds.values() for e in room if e['data'].get('type')=='executionActivity' and e['data'].get('phase')=='completed' and e['data'].get('nativeType')=='commandExecution']
  mark('peer-and-global-real-native-command-activity',all(any(e['data']['agentId']==actor for e in actions) for actor in [a['agent'],peer['agent']]))
  detail['commandActivityEventIds']=[e['id'] for e in actions]
  detail['globalCommandsForReview']=[{'event':e['id'],'command':e['data'].get('command'),'output':e['data'].get('output'),'sequence':e['seq']} for e in actions if e['data']['agentId']==a['agent']]
  mark('all-owned-deliveries-terminal',all(d['state'] in ['completed','failed','cancelled'] for d in deliveries))
  mark('own-eight-units-stopped',len(retire['pids'])==8 and all(subprocess.check_output(['systemctl','show',u,'-p','MainPID','--value'],text=True).strip()=='0' for u in retire['pids']))
  mark('protected-production-services-unchanged',retire['protectedPidsUnchanged'] and all(subprocess.check_output(['systemctl','show',u,'-p','MainPID','--value'],text=True).strip()==pid for u,pid in retire['protectedPids'].items()))
  proof={'at':time.time(),'checks':checks,'passed':all(checks.values()),'detail':detail,'originalResultSha256':sha(RUN/'result.json'),'scope':'Independent actual-state/authenticated API/native evidence audit of same frozen trial, no new model trial. Global command transcripts still need explicit review for actual independent file verification; no typed server-enforced goal-definition guarantee.'}
  (Q/'role-goal-independent-audit-r258.json').write_text(json.dumps(proof,indent=2)+'\n')
  print(json.dumps({'passed':proof['passed'],'checks':checks,'failed':[k for k,v in checks.items() if not v]}))
  if not proof['passed']:raise SystemExit(1)
if __name__=='__main__':main()
