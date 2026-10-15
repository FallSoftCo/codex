"""Real Global provisions and delivers despite lost administrative acknowledgements."""
import hashlib,json,os,pwd,secrets,socket,subprocess,time,urllib.request
from pathlib import Path
from uuid import uuid4
from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.store import Store,json_value
from lax_connector.linux_admin import provision
from lax_connector.host import enroll,resources
from lax_connector.journal import saved

PROXY = 'import json,sys\nfrom pathlib import Path\nfrom aiohttp import web,ClientSession\nroot=Path(sys.argv[1]);trace=[]\nasync def forward(req):\n if req.path=="/health":return web.json_response({"service":"owned-administrative-receipt-fault"})\n body=await req.read();payload=json.loads(body)if body else {}\n operation=payload.get("operationId","")\n kind=None\n if operation.startswith("lax-tool:")and ":admin:"in operation:\n  kind=operation.rsplit(":admin:",1)[1]\n async with ClientSession()as session:\n  async with session.request(req.method,"http://127.0.0.1:18772"+req.path_qs,data=body,headers={k:v for k,v in req.headers.items()if k.lower()in("authorization","content-type")},allow_redirects=False)as response:\n   data=await response.read()\n   dropped=bool(kind in("principal","role","room","placement")and response.status==200 and not(root/("lost-"+kind+".json")).exists())\n   trace.append({"method":req.method,"path":req.path,"upstream":response.status,"ackDropped":dropped,"kind":kind,"operationId":operation});(root/"proxy-trace.json").write_text(json.dumps(trace))\n   if dropped:\n    (root/("lost-"+kind+".json")).write_text(json.dumps({"operationId":operation,"acceptedResult":json.loads(data)}))\n    return web.json_response({"error":"Owned qualification dropped an accepted administrative acknowledgement"},status=503)\n   return web.Response(body=data,status=response.status,content_type="application/json")\napp=web.Application();app.router.add_route("*","/{tail:.*}",forward)\nweb.run_app(app,host="127.0.0.1",port=18773,print=None)\n'
LOCAL_CALLBACK_FAULT = 'import json,sys\nfrom pathlib import Path\nimport lax_connector.connector as module\nimport lax_connector.administration as admin\nfrom lax_connector.journal import saved\nconfig=json.loads(Path(sys.argv[sys.argv.index("--config")+1]).read_text())\nflag=Path(config["state"])/"qualification-provision-result-gap.json"\nclass ResultBoundary:\n def __getattr__(self,name):return getattr(json,name)\n def loads(self,raw,*args,**kwargs):\n  value=json.loads(raw,*args,**kwargs)\n  if isinstance(value,dict)and value.get("schema")=="lax-worker-provision/v1"and value.get("state")=="resident-enabled"and not flag.exists():\n   saved(flag,{"fault":"Actual root provisioning completed; original stdout interpretation lost once","agentId":value["agentId"],"unit":value["unit"],"specDigest":value["specDigest"]})\n   raise OSError("Owned qualification lost accepted provisioning result")\n  return value\nadmin.json=ResultBoundary()\nmodule.main()\n'

def main():
 os.umask(0o077);assert os.geteuid()==0 and socket.gethostname()=="ozzz-aosp"
 root=Path(os.environ["NATIVE_COMMAND_EVIDENCE"]);root.mkdir(mode=0o711);root.chmod(0o711)
 runtime=Path(os.environ["NATIVE_COMMAND_RUNTIME"]);python=str(runtime/"venv/bin/python");dbp=Path(os.environ["NATIVE_COMMAND_DATABASE_CONFIG"])
 for port in(18772,18773):
  with socket.socket()as s:s.bind(("127.0.0.1",port))
 initialize(json.loads(dbp.read_text()),root/"enterprise","Actual native administrative recovery")
 setup=json.loads((root/"enterprise/installation-intent.json").read_text());authority=setup["authorityId"];owner=setup["credentials"]["Owner"];glob=setup["credentials"]["Global"];room=setup["globalRoomId"];host=str(uuid4())
 store=Store(json.loads(dbp.read_text()));children=[];unit=None;g=None
 saved(root/"intent.json",{"scope":"One fresh finite actual Global/worker mission; lost administrative and provisioning acknowledgements; one independent material review","productionChanged":False,"physicalPhoneChanged":False,"runtime":str(runtime)})
 saved(Path("/opt/hetzner-blue-team/coordination/announcements")/("native-command-recovery-"+authority+".json"),{"owner":"01a12c58-d21a-79b0-a512-0c3bc6dc0ee4","host":"ozzz-aosp","privateListeners":["127.0.0.1:18772","127.0.0.1:18773"],"scope":"Fresh finite native Global/worker receipt recovery only; no historical owner wake","runtime":str(runtime),"credentialIntent":str(root/"enterprise/installation-intent.json"),"rollback":"Stop only owned Global/worker/controller/API/proxy; retain exact receipts"})
 def launch(name,args):
  with(root/(name+".log")).open("ab")as f:p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT)
  children.append(p);saved(root/(name+"-process.json"),{"pid":p.pid});return p
 def stop(p):
  if p and p.poll()is None:p.terminate();p.wait(timeout=20)
 def ready(base,p):
  for _ in range(100):
   assert p.poll()is None
   try:
    with urllib.request.urlopen(base+"/health",timeout=2)as response:
     if response.status==200:return
   except OSError:time.sleep(.2)
  raise RuntimeError("Owned service readiness timed out")
 def api(path,body=None,name=None):
  if body is not None:
   assert name;saved(root/(name+"-intent.json"),{"path":path,"body":body})
  request=urllib.request.Request("http://127.0.0.1:18772/hollywood/v3/"+path,method="POST"if body is not None else"GET",data=None if body is None else json.dumps(body).encode(),headers={"Authorization":"Bearer "+owner["token"],"Content-Type":"application/json"})
  with urllib.request.urlopen(request,timeout=15)as response:value=json.load(response)
  if name:saved(root/(name+"-receipt.json"),value)
  return value
 def workers():return [json.loads(p.read_text())for p in(Path("/var/lib/harness")/authority/"workers").glob("*/provision-receipt.json")]
 def wait(test,seconds):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   value=test()
   if value:return value
   time.sleep(.5)
  raise RuntimeError("Finite native command recovery timed out")
 def state():
  with store.pool.connection()as c:
   goals=c.execute("SELECT id,state FROM hb_goal WHERE authority=%s",(authority,)).fetchall()
   work=c.execute("SELECT id,state,evidence FROM hb_work WHERE authority=%s",(authority,)).fetchall()
   deliveries=c.execute("SELECT id,agent,state,native_thread,native_turn FROM hb_delivery WHERE authority=%s ORDER BY updated_at",(authority,)).fetchall()
  return json_value({"goals":goals,"work":work,"deliveries":deliveries})
 try:
  api_process=launch("api",[python,"-m","hollywood_backbone.server","--database-config",str(dbp),"--port","18772"]);ready("http://127.0.0.1:18772",api_process)
  proxy=root/"proxy.py";proxy.write_text(PROXY);proxy_process=launch("proxy",[python,str(proxy),str(root)]);ready("http://127.0.0.1:18773",proxy_process)
  g=provision({"installationIntent":str(root/"enterprise/installation-intent.json"),"approvedModelAuthFile":os.environ["NATIVE_COMMAND_APPROVED_AUTH"],"binary":str(runtime/"native/bin/codex"),"interpreter":python,"hollywoodUrl":"http://127.0.0.1:18773","hostId":host,"model":"gpt-6.1-sol","effort":"xhigh"});saved(root/"global-provision-receipt.json",g)
  api("placements",{"hostId":host,"name":"Native administrative recovery OZZZ","identityFingerprint":hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest(),"capabilities":{"localProvisioning":True},"agentId":glob["principalId"]},"placement")
  enrolled=enroll({"authorityId":authority,"hostId":host,"hollywoodUrl":"http://127.0.0.1:18773","administratorCredential":owner,"policy":{"maxConcurrent":resources()["cpuSlots"],"reservedInteractive":1 if resources()["cpuSlots"]>1 else 0,"controlAgentIds":[glob["principalId"]],"memoryPerTurnBytes":2*1024**3,"reserveMemoryBytes":4*1024**3,"sampleMaxAgeSeconds":20,"connectorMaxAgeSeconds":20}});saved(root/"host-enrollment.json",enrolled)
  subprocess.run([python,"-m","lax_connector.host","--once",enrolled["configPath"]],capture_output=True,check=True);launch("host-controller",[python,"-m","lax_connector.host","--serve",enrolled["configPath"]])
  wrapper=runtime/"qualification-provision-result-gap.py";wrapper.write_text(LOCAL_CALLBACK_FAULT);wrapper.chmod(0o644)
  unit="lax-admin-global-"+authority.replace("-","")[:12];saved(root/"global-service-intent.json",{"unit":unit})
  subprocess.run(["systemd-run","--unit="+unit,"--uid="+g["linuxUser"],"--property=UMask=0077","--property=MemoryMax=3G","--property=RuntimeMaxSec=1200","--property=WorkingDirectory="+g["home"]+"/work",python,str(wrapper),"--config",g["connectorConfig"],"--serve"],capture_output=True,check=True)
  marker="ORIGINAL_RECEIPT_"+secrets.token_hex(12);saved(root/"expected-marker.json",{"marker":marker})
  task=("Run one finite Global-to-worker enterprise deliverable. Create one fresh engineer, its Engineering room and home work role, and provision its separate non-sudo Linux execution. Create one goal titled Original command receipt delivery, objective Produce and independently verify an actual worker artifact despite lost transport acknowledgements, acceptance The worker file receipt-proof.txt contains exactly "+marker+" and newline, its connector evidence matches the file, Global independently verifies bytes/hash and explicitly accepts the work and goal. Set reviewBudget=1 for one material completion review. Add and assign exactly one work to that engineer: read the briefing, write exactly "+marker+" and newline to receipt-proof.txt in its workspace, verify actual bytes/hash, complete its bounded native goal and submit artifactPaths receipt-proof.txt with current revision. Do not ask a question, create extra workers or poll models. End the initial Global turn promptly after delegation. In the one material completion review, read canonical work/evidence, independently inspect the actual file through your host administration and accept work/goal only after verification. Keep the ongoing Global role active. Do not replay uncertain operations, schedule, self-chain or touch historical work.")
  api("rooms/"+room+"/messages",{"operationId":"native-command:"+str(uuid4()),"kind":"request","body":task,"recipientId":glob["principalId"],"audience":"room"},"original-request")
  def accepted():
   s=state();return s if len(s["goals"])==1 and s["goals"][0]["state"]=="accepted"and len(s["work"])==1 and s["work"][0]["state"]=="accepted"and len(s["deliveries"])==3 and all(d["state"]=="completed"for d in s["deliveries"])else None
  completed=wait(accepted,660)
  current=workers();assert len(current)==1;worker=current[0]
  assert(Path(worker["workspace"])/"receipt-proof.txt").read_text()==marker+"\n"
  global_state=Path(g["home"])/"state"
  root_tools=[json.loads(p.read_text())for p in global_state.glob("tool-*.json")]
  assert all(t["state"]=="completed"for t in root_tools)
  provision_tools=[t for t in root_tools if t["tool"]=="lax_provision_worker"]
  assert len(provision_tools)==1 and provision_tools[0]["result"]["success"]
  provision_result=json.loads(provision_tools[0]["result"]["contentItems"][0]["text"])
  assert provision_result["recoveredBy"]=="protected-original-provisioning-read"
  assert provision_result["inspection"]["modelOrServiceRestarted"]is False
  assert(global_state/"qualification-provision-result-gap.json").exists()
  recovered=[]
  for path in global_state.glob("effects-*.json"):
   value=json.loads(path.read_text())
   for step in value["steps"]:
    if step.get("recoveredBy")=="original-administrative-command-read":
     assert step["wireRequest"]is None
     recovered.append({"operationId":step["operationId"],"wireDigest":step["wireDigest"]})
  trace=json.loads((root/"proxy-trace.json").read_text())
  for kind in("principal","role","room","placement"):
   lost=json.loads((root/("lost-"+kind+".json")).read_text());operation=lost["operationId"]
   calls=[x for x in trace if x.get("operationId")==operation and x["method"]in("POST","PUT")]
   assert len(calls)==1 and calls[0]["ackDropped"]
   assert any(x["operationId"]==operation for x in recovered)
  subprocess.run(["systemctl","disable","--now",worker["unit"]],capture_output=True,check=True)
  spec=global_state/("worker-provision-"+worker["agentId"]+".json")
  def inspect(specpath):
   return subprocess.run([python,"-m","lax_connector.linux_worker","--spec",str(specpath),"--inspect"],capture_output=True,text=True)
  observed=inspect(spec);assert observed.returncode==0
  original=json.loads(observed.stdout)
  assert original["inspection"]["currentService"]["ActiveState"]=="inactive"
  assert original["inspection"]["currentService"]["UnitFileState"]=="disabled"
  assert original["inspection"]["currentService"]["MainPID"]=="0"
  saved(root/"stopped-worker-inspection.json",original)
  bad=json.loads(spec.read_text());bad["machineIdentity"]="0"*64;saved(root/"wrong-host-spec.json",bad)
  assert inspect(root/"wrong-host-spec.json").returncode!=0
  bad=json.loads(spec.read_text());bad["effort"]="low";saved(root/"wrong-content-spec.json",bad)
  assert inspect(root/"wrong-content-spec.json").returncode!=0
  boundary=Path(worker["workspace"])/".qualification-inspection-boundary.json"
  assert not boundary.exists();boundary.write_text("{}");os.chown(boundary,worker["uid"],pwd.getpwnam(worker["linuxUser"]).pw_gid)
  try:
   unauthorized=subprocess.run(["runuser","-u",worker["linuxUser"],"--",python,"-m","lax_connector.linux_worker","--spec",str(boundary),"--inspect"],capture_output=True)
   assert unauthorized.returncode!=0 and b"Provisioning inspection requires verified administration"in unauthorized.stderr
  finally:boundary.unlink()
  result={"passed":True,"actualNativeTurns":3,"globalContexts":1,"workerContexts":1,
   "administrativeChildAcknowledgementsRecovered":4,"acceptedAdministrativeChildPostsRepeated":0,
   "actualProvisioningResultRecoveredByReadOnlyInspection":True,
   "stoppedWorkerPreservedByInspection":True,"wrongHostAndChangedSpecDenied":True,
   "unprivilegedInspectionDenied":True,"originalArtifactIndependentlyAccepted":True,
   "artifactSha256":hashlib.sha256((Path(worker["workspace"])/"receipt-proof.txt").read_bytes()).hexdigest(),
   "actualState":completed,"recoveredChildren":recovered,
   "modelPolling":False,"originalTaskResubmitted":False,"productionChanged":False,"physicalPhoneChanged":False}
  saved(root/"result.json",result);print(json.dumps(result),flush=True)
 finally:
  for w in workers():subprocess.run(["systemctl","disable","--now",w["unit"]],capture_output=True)
  if unit:subprocess.run(["systemctl","stop",unit],capture_output=True)
  for child in reversed(children):stop(child)
  saved(root/"cleanup.json",{"ownedChildrenStopped":all(p.poll()is not None for p in children),"ownedGlobalStopped":True,"ownedWorkersStoppedDisabled":True,"productionChanged":False})
  store.close()

if __name__=="__main__":main()
