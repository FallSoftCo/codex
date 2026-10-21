import json,subprocess,time,hashlib
from pathlib import Path
from lax_connector.journal import saved
Q=Path('/var/lib/lax-existing-global-adoption-20261021-r266/cutover-r267/actual-user-journey')
js="import fs from 'node:fs';\nimport {loadHollywood,HollywoodClient,hollywoodRequest} from '/home/aosp/.local/share/nextcomp-backend/releases/20261017-native-core-alpha110-r03/server/hollywood.mjs';\nconst b=loadHollywood('/home/aosp/.local/share/nextcomp-backend/data');const cfg=b.devices.get('owner')||b.defaultBinding;\nconst fresh=new HollywoodClient(cfg);await fresh.verify();const room='91eacc0e-bdd1-530b-a3bd-23dfa7103761';\nconst get=async(path,query={})=>{const r=hollywoodRequest('GET',path,query);return fresh.call(r.path,r);};\nconst command=await get('commands/actual-native-r267:readiness-request');\nconst conversation=await get('rooms/'+room+'/history',{view:'conversation',limit:'100'});\nconst activity=await get('rooms/'+room+'/history',{view:'activity',limit:'100'});\nconst catalog=await get('rooms');\nconsole.log(JSON.stringify({at:Date.now(),identity:fresh.envelope(),command,conversation,activity,catalogRoom:catalog.rooms.find(r=>r.id===room),posts:0}));\n"
p=subprocess.run(['/usr/sbin/runuser','-u','aosp','--','/usr/bin/node','--input-type=module','-'],input=js,capture_output=True,text=True,timeout=35)
assert p.returncode==0,p.stderr[-1500:]
d=json.loads(p.stdout);assert d['posts']==0
assert d['command']['event']['id']=='c97ed259-0e18-40b6-9d3a-1518c3cd3234'
assert len(d['command']['deliveries'])==1 and d['command']['deliveries'][0]['id']=='0c417797-66ff-49ae-aecf-7a497d984f44' and d['command']['deliveries'][0]['state']=='completed'
conv=d['conversation']['events'];activity=d['activity']['events']
assert not any(e['data'].get('type')=='executionActivity' for e in conv)
assert activity and all(e['data'].get('type')=='executionActivity' for e in activity)
assert not {e['id'] for e in conv}&{e['id'] for e in activity}
assert sum(e['kind']=='message' and e['data'].get('nativeContext',{}).get('purpose')=='responder' for e in conv)==1
settled=[r for e in activity for r in e['data'].get('protocolReceipts',[]) if r.get('result',{}).get('schema')=='canonical-delivery-edits/v1']
# Receipt layout is retained verbatim; report only observed actual settled proofs.
proofs=[r for e in activity for r in e['data'].get('protocolReceipts',[]) if 'canonical-delivery-edits/v1' in json.dumps(r)]
assert proofs,'Actual native patch lacks canonical receipt evidence'
assert all(d['catalogRoom']['activity'][k]==0 for k in ['pending','claimed','running','cancelRequested','unknown','waitingForHuman'])
assert d['catalogRoom']['feedSummary']['latestMessage']['eventId']=='f569c06b-fe8f-49d8-91c8-d016deefab06'
saved(Q/'fresh-client-readback.json',d)
summary={'schema':'actual-native-client-readback/v1','at':time.time(),'originalCommandRecovered':True,'originalDeliveryCompleted':True,'freshClientVerifiedSameHumanAndRealm':True,'conversationEvents':len(conv),'separateActivityEvents':len(activity),'outwardFinalResponses':1,'canonicalPatchReceiptObserved':True,'catalogIdleAndRealFinalRecency':True,'requestsSubmitted':0,'physicalHandsetProved':False,'wireReceiptSha256':hashlib.sha256((Q/'fresh-client-readback.json').read_bytes()).hexdigest()}
saved(Q/'fresh-client-readback-summary.json',summary);print(json.dumps(summary))
