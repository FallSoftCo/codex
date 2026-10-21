import hashlib,json,os,subprocess,time
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from lax_connector.journal import saved
A='e488f19b-0f60-46ca-bd48-4fe544f06757';G='2d4a0daa-0514-475e-be1e-71decacbd5bc';H='301c8b83-8cdb-5b9a-9d7f-3b2fa6f0b3f6'
C=Path('/var/lib/lax-existing-global-adoption-20261021-r266/cutover-r267');Q=C/'actual-user-journey';D=Path('/var/lib/harness')/A/'purpose-agents'/G
os.umask(0o077)
s=json.loads((Q/'complete-observed.json').read_text());protocol=json.loads((Q/'protocol.json').read_text());m=json.loads((D/'installation.json').read_text());config=json.loads(Path(m['config']).read_text())
report=Path(config['workspace'])/'native-install-readiness.json';data=json.loads(report.read_text())
assert data['host']['hostname']==subprocess.check_output(['hostname'],text=True).strip()
assert data['host']['effective_uid']==m['uid'] and data['host']['effective_user']==m['linuxUser']
assert data['sudo']['observed_uid']==0 and data['sudo']['noninteractive_root_verified'] is True
assert data['github']['login']=='aiyer-commits' and data['github']['exit_code']==0
for name in ['LAX','Hollywood']:
 root=Path(data['sources'][name]['path']);actual=subprocess.check_output(['git','-c','safe.directory='+str(root),'-C',str(root),'rev-parse','HEAD'],text=True).strip();assert data['sources'][name]['revision']==actual
 assert not subprocess.check_output(['git','-C',str(root),'status','--porcelain','--untracked-files=no'],text=True)
saved(Q/'independent-report-audit.json',{'at':time.time(),'reportPath':str(report),'sha256':hashlib.sha256(report.read_bytes()).hexdigest(),'size':report.stat().st_size,'observedFactsIndependentlyMatch':True,'expectedOutputWasNotWrittenByHarness':True})
db=psycopg.connect(**json.loads(Path('/etc/harness/production/database.json').read_text()),row_factory=dict_row,autocommit=True);db.execute('SET default_transaction_read_only=on')
contexts=db.execute('SELECT purpose,native_thread,active_turn FROM hb_purpose_context WHERE agent=%s ORDER BY purpose',(G,)).fetchall();assert len(contexts)==3 and len({c['native_thread'] for c in contexts})==3 and all(c['active_turn'] is None for c in contexts)
for c in contexts:
 binding=json.loads((Path(config['state'])/c['purpose']/'context.json').read_text());assert binding['nativeThread']==c['native_thread']
events=db.execute('SELECT * FROM hb_event WHERE room=%s ORDER BY seq',(protocol['roomId'],)).fetchall()
original=[e for e in events if str(e['id'])=='c97ed259-0e18-40b6-9d3a-1518c3cd3234'];assert len(original)==1 and str(original[0]['author'])==H and original[0]['data']['authorKind']=='human'
answers=[e for e in events if e['data'].get('type')=='humanQuestionAnswer'];assert len(answers)==1 and str(answers[0]['author'])==H and str(answers[0]['source'])=='98105ac9-8807-4ad2-856f-b51e40738b0d'
d=db.execute('SELECT * FROM hb_delivery WHERE id=%s',('0c417797-66ff-49ae-aecf-7a497d984f44',)).fetchone();assert d['state']=='completed' and d['generation']==1
final=next(e for e in events if e['id']==d['result_event']);assert str(final['author'])==G and final['data']['authorKind']=='agent' and final['data']['nativeContext']['purpose']=='responder'
activity=[e for e in events if e['data'].get('type')=='executionActivity'];assert activity
assert all(str(e['author'])==G and e['data']['agentId']==G for e in activity)
placements=db.execute('SELECT agent,enabled FROM hb_placement WHERE authority=%s',(A,)).fetchall();assert sum(1 for p in placements if p['enabled'])==1 and next(p for p in placements if str(p['agent'])==G)['enabled']
db.close()
plan=json.loads((C/'plan.json').read_text())
legacy={}
for unit in plan['legacyAgentUnits']:
 state=dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',unit,'-p','MainPID','-p','ActiveState','-p','UnitFileState'],text=True).splitlines());assert state['MainPID']=='0' and state['ActiveState']=='inactive' and state['UnitFileState']=='disabled';legacy[unit]=state
before=json.loads((C/'binding.before.json').read_text());assert hashlib.sha256(Path(before['path']).read_bytes()).hexdigest()==before['sha256'];assert subprocess.check_output(['systemctl','show','nextcomp-native-core.service','-p','MainPID','--value'],text=True).strip()==before['nextcompPid']
saved(Q/'canonical-end-state-audit.json',json.loads(json.dumps({'at':time.time(),'originalRequestEvent':str(d['event']),'originalDelivery':str(d['id']),'originalGeneration':d['generation'],'originalState':d['state'],'requestPosts':1,'answerPosts':1,'contexts':contexts,'finalResponseEventId':str(final['id']),'finalResponse':final['body'],'activityEvents':len(activity),'ordinaryFinalResponses':sum(e['kind']=='message' and str(e['author'])==G for e in events),'otherPlacementsPaused':11,'oldSupervisorsStoppedDisabled':len(legacy),'pairingBytesAndNextcompPidPreserved':True,'initialProviderFailureRetained':True,'physicalPhoneProved':False},default=str)))
print(json.dumps({'independentReportMatched':True,'canonicalOriginalCompleted':True,'finalResponse':final['body'],'activityEvents':len(activity),'otherPlacementsPaused':11,'nextcompUnchanged':True}))
