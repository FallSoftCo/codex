"""Post-trial independent readback; original frozen results remain unchanged."""
import json,time,hashlib,runpy,subprocess
from pathlib import Path
from lax_connector.host import request
from hollywood_backbone.store import Store
ROOT=Path('/var/lib/lax-standing-responsibility-20261020-r242')
Q=Path('/aosp/development/lax-three-context-20261018-r01/qualification')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pid(u):return subprocess.check_output(['systemctl','show',u,'-p','MainPID','--value'],text=True).strip()
def wire(v):return json.loads(json.dumps(v,default=str))
scorer=runpy.run_path(str(Q/'standing_outcome_r242.py'))
store=Store(json.loads(Path('/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json').read_text()))
report={'at':time.time(),'kind':'Post-trial actual state/history and independent artifact audit, not a new model trial or replacement frozen score','arms':{}}
try:
 for name in ['baseline','candidate']:
  base=ROOT/name;run=base/'run';arm=json.loads((base/'public.json').read_text());peer=json.loads((base/'peer/public.json').read_text());plan=json.loads((base/'installation-intent.json').read_text())
  result=json.loads((run/'result.json').read_text());retire=json.loads((run/'retirement.json').read_text())
  assert result['state']=='observed' and retire['error'] is None
  checks={};detail={}
  checks['same-six-history-bindings']=result['sameSixHistories'] and len(result['histories'])==6
  checks['all-owned-units-stopped']=all(pid(u)=='0' for u in retire['pids'])
  checks['no-unsettled-native-turns']=all(c['active_turn'] is None for c in retire['preStopContexts'])
  checks['protected-services-unchanged']=all(pid(u)==v for u,v in retire['protectedPids'].items()) and retire['protectedPidsUnchanged']
  phases={x['phase']:x for x in result['phases']};release=phases['release']
  contract=scorer['expected'](json.loads((ROOT/'protocol/RELEASE-REQUIREMENTS.json').read_text()))
  checks['actual-engineering-release-matches-frozen-requirements']=release['artifact']['expected']==contract
  checks['no-new-consumer-human-assignment']=release['noConsumerHumanRequest']
  checks['original-receipt-remains-completed']=release['originalStillComplete']
  checks['unrelated-room-input-no-work-or-reply']=all(phases['unrelated'][k] for k in ['noNewWork','noReply','outputUnchanged'])
  checks['unchanged-repeated-fact-no-work-or-reply']=all(phases['repeat'][k] for k in ['noNewWork','noReply','outputUnchanged'])
  checks['withdrawn-role-no-work-or-reply']=all(phases['role-withdrawal'][k] for k in ['noNewWork','noReply','outputUnchanged'])
  # Actually read authenticated human history, paginating from original sequence.
  history=[];cursor=0;pages=0
  while True:
   response=request(arm['url'],plan['credentials']['Owner']['token'],'GET','rooms/'+arm['room']+'/history?view=all&limit=100&after='+str(cursor))
   pages+=1;history.extend(response['events'])
   following=response.get('nextCursor')
   if not response['events'] or following is None or following==cursor:break
   cursor=following
   assert pages<100
  finals=[d['result_event'] for d in result['snapshot']['deliveries'] if d['agent']==arm['agent'] and d['state']=='completed']
  checks['human-api-final-results-visible']=all(any(e['id']==i for e in history) for i in finals) and bool(finals)
  detail['humanHistoryPages']=pages
  native_roles=[e for e in history if e['kind']=='control' and e['data'].get('type')=='roleWork']
  if name=='candidate':
   checks['one-bounded-follow-on']=release['newBoundedWork'] and len(native_roles)==1 and len(release['followOnDeliveries'])==1 and release['followOnDeliveries'][0]['state']=='completed'
   checks['correct-actual-follow-on']=release['correctOutput'] and release['artifact']['actual']==contract and release['sourceProvenance']
   checks['frozen-unseen-and-invalid-cases']=all(x['passed'] for x in release['unseenAndInvalid'])
   role=native_roles[0];source=next(e for e in history if e['id']==role['source'])
   initial=phases['initial']['originalDelivery'];final=next(e for e in history if e['id']==initial['result_event'])
   checks['initiative-source-is-real-peer-report']=source['author']==peer['agent'] and source['kind']=='message' and source['data'].get('authorKind')=='agent' and source['data'].get('nativeContext',{}).get('purpose')=='responder'
   checks['initial-completed-before-peer-report-before-initiative']=final['seq']<source['seq']<role['seq']
   checks['native-control-not-human-or-chat-self-request']=role['author']==arm['agent'] and role['data']['authorKind']=='agent' and not any(e['kind']=='request' and e['author']==e.get('recipient') for e in history)
   checks['private-role-not-in-public-event']='roleSnapshot' not in role['data'] and 'role' not in role['data'] and 'interpretation' not in role['data']
   with store.pool.connection() as c:
    material=c.execute("SELECT * FROM hb_context_material WHERE agent=%s AND kind='work' AND source=%s",(arm['agent'],role['id'])).fetchone()
    captured=material['value']['roleInitiative']
    checks['captured-role-snapshot-matches-public-digest']=captured['roleRevision']==role['data']['roleRevision'] and __import__('hollywood_backbone.store',fromlist=['digest']).digest(captured['roleSnapshot'])==role['data']['roleSha256']
    checks['source-observation-handled-on-original-id']=c.execute('SELECT state,value FROM hb_context_material WHERE id=%s',(captured['observationId'],)).fetchone()['value']['initiatedWorkId']==str(material['id'])
   # A second artifact probe is supplementary evidence, not another model run.
   supplementary=scorer['probe'](Path(arm['workspace'])/'build_bulletin.py',scorer['cases'](ROOT/'protocol'))
   checks['delivered-cli-reverified']=all(x['passed'] for x in supplementary)
   detail.update(roleEventId=role['id'],externalPeerEventId=source['id'],sourceHostPathAndSha256=release['artifact']['source'],supplementaryCases=supplementary)
  else:
   checks['baseline-gap-retained']=not release['newBoundedWork'] and not release['correctOutput'] and not native_roles
  report['arms'][name]={'checks':checks,'passed':all(checks.values()),'detail':detail,'seconds':result['seconds'],'nativeResultSha256':digest(run/'result.json'),'retirementSha256':digest(run/'retirement.json')}
 out=Q/'standing-role-independent-audit-r246.json';out.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({n:{'passed':r['passed'],'checks':r['checks']} for n,r in report['arms'].items()}))
finally:store.close()
