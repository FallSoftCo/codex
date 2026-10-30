"""Real HTTP observer lanes and durable lost-reply recovery; no native workers."""
import json,threading,time,sys
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from lax_connector import host

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
local,remote=str(uuid4()),str(uuid4());accepted={};attempts=[];lock=threading.Lock();fail_remote=True
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  global fail_remote
  node=self.headers.get('X-Hollywood-Host-Node');assert node in (local,remote)
  p=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  if node==remote:time.sleep(.4)
  key=(node,p['operationId'])
  with lock:
   accepted.setdefault(key,{'accepted':True,'operationId':p['operationId']})
   attempts.append((node,p['operationId'],time.monotonic()))
   failure=node==remote and fail_remote
   if failure:fail_remote=False
  self.send_response(503 if failure else 200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'error':'SYNTHETIC lost reply after commit'} if failure else accepted[key]).encode())
 def do_GET(self):
  assert self.headers.get('X-Hollywood-Host-Node') in (local,remote)
  assert self.path.endswith('/executors')
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"executors":[],"nextAfter":null}')
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
config={'state':str(out/'state'),'machineIdentity':host.machine_identity(),'hostId':str(uuid4()),'authorityId':str(uuid4()),'hollywoodUrl':'http://127.0.0.1:'+str(server.server_port),'token':'SYNTHETIC-NOT-A-CREDENTIAL','observationNodes':[local,remote]}
try:
 with patch('lax_connector.purpose_observer.reconcile',return_value={'held':0}),patch('lax_connector.service_restart.reconcile_services',return_value={'held':0}):
  first=host.supervise(config,once=True)
  assert [v['state'] for v in first['sources']]==['healthy','held']
  pending=json.loads((out/'state'/('node-'+remote+'-sample-intent.json')).read_text());assert pending['state']=='pending'
  local_at=next(a[2] for a in attempts if a[0]==local);remote_at=next(a[2] for a in attempts if a[0]==remote);assert local_at<remote_at-.2
  second=host.supervise(config,once=True);assert all(v['state']=='healthy' for v in second['sources'])
  remote_ops=[a[1] for a in attempts if a[0]==remote];assert remote_ops==[pending['payload']['operationId']]*2
  assert len(accepted)==3 and len(attempts)==4
  assert json.loads((out/'state'/'observation-sources.json').read_text())['state']=='healthy'
 result={'passed':True,'actualHTTP':True,'localObservationNotDelayedByRemote':True,'failedSourceRetainsOriginalOperation':True,'sameIdRecoveryNoDuplicateAcceptance':True,'independentNodeJournals':True,'acceptedOperations':3,'requests':4,'modelsStarted':0,'productionChanged':False}
 (out/'qualification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
finally:server.shutdown();server.server_close();thread.join(timeout=2)
