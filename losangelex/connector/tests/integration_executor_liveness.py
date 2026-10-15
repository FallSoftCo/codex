"""Real native process/systemd/PG resource proof; zero provider inference."""
import hashlib,json,os,socket,subprocess,time,urllib.request,urllib.error
from pathlib import Path
from uuid import uuid4
from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.store import Store,json_value
from lax_connector.linux_admin import provision
from lax_connector.host import enroll,supervise,request
from lax_connector.service_observer import register,observe
from lax_connector.connector import CAPABILITIES
from lax_connector.journal import saved

GUARDIAN = 'import asyncio,json,os,sys\nfrom pathlib import Path\nfrom lax_connector.rpc import AppServer\nfrom lax_connector.service_observer import process,boot_id\nfrom lax_connector.host import machine_identity\nfrom lax_connector.journal import saved\nconfig=json.loads(Path(sys.argv[1]).read_text());root=Path(config["state"])/"executor-qualification";root.mkdir(mode=0o700)\nasync def event(method,params):pass\nasync def request(method,params):raise RuntimeError("Metadata-only native runtime received unexpected callback")\nasync def waitflag(name):\n for _ in range(1200):\n  if(root/name).exists():return\n  await asyncio.sleep(.1)\n raise RuntimeError("Finite guardian control timed out")\nasync def main():\n rpc=AppServer(config["binary"],Path(config["codexHome"]),root/"native",event,request)\n helper=None\n try:\n  await rpc.start()\n  helper=await asyncio.create_subprocess_exec("/usr/bin/sleep","150")\n  own=process(os.getpid());native=process(rpc.process.pid)\n  saved(root/"descriptor.json",{"machineIdentity":machine_identity(),"bootId":boot_id(),\n   "serviceUnit":sys.argv[2],"serviceInvocation":os.environ["INVOCATION_ID"],\n   "controlGroup":own["controlGroup"],"guardianPid":own["pid"],"guardianStart":own["start"],\n   "nativePid":native["pid"],"nativeStart":native["start"]})\n  saved(root/"helper.json",{"pid":helper.pid,"start":process(helper.pid)["start"]})\n  await waitflag("close-native");await rpc.close();saved(root/"native-closed.json",{"originalNativeStopped":rpc.process.returncode is not None})\n  await waitflag("stop-helper");helper.terminate();await helper.wait();saved(root/"helper-stopped.json",{"helperStopped":True})\n  await waitflag("finish")\n finally:\n  if helper and helper.returncode is None:helper.terminate();await helper.wait()\n  await rpc.close()\nasyncio.run(main())\n'

def main():
 os.umask(0o077);assert os.geteuid()==0 and socket.gethostname()=="ozzz-aosp"
 root=Path(os.environ["EXECUTOR_EVIDENCE"]);root.mkdir(mode=0o711);root.chmod(0o711)
 runtime=Path(os.environ["EXECUTOR_RUNTIME"]);python=str(runtime/"venv/bin/python")
 dbp=Path(os.environ["EXECUTOR_DATABASE_CONFIG"]);store=Store(json.loads(dbp.read_text()))
 with socket.socket()as s:s.bind(("127.0.0.1",18772))
 initialize(json.loads(dbp.read_text()),root/"enterprise","Executor resource lifecycle")
 setup=json.loads((root/"enterprise/installation-intent.json").read_text());a=setup["authorityId"];people=setup["credentials"];host=str(uuid4());room=setup["globalRoomId"]
 api=None;unit=None;g=None;checks=[]
 def call(who,method,path,body=None,status=200):
  token=people[who]["token"]
  req=urllib.request.Request("http://127.0.0.1:18772/hollywood/v3/"+path,method=method,
   data=None if body is None else json.dumps(body).encode(),
   headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
  try:
   with urllib.request.urlopen(req,timeout=15)as response:value=json.load(response);code=response.status
  except urllib.error.HTTPError as error:code=error.code;value=json.load(error)
  assert code==status,(method,path,code,status)
  return value
 def wait(test,seconds=40):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   value=test()
   if value:return value
   time.sleep(.2)
  raise RuntimeError("Bounded resource qualification timed out")
 def flag(name):
  p=Path(g["home"])/"state/executor-qualification"/name;p.write_text("one explicit qualification control");p.chmod(0o644)
 try:
  with(root/"api.log").open("ab")as log:
   api=subprocess.Popen([python,"-m","hollywood_backbone.server","--database-config",str(dbp),"--port","18772"],stdout=log,stderr=subprocess.STDOUT)
  def healthy():
   assert api.poll()is None
   try:
    with urllib.request.urlopen("http://127.0.0.1:18772/health",timeout=2)as response:return response.status==200
   except OSError:return False
  wait(healthy)
  g=provision({"installationIntent":str(root/"enterprise/installation-intent.json"),"approvedModelAuthFile":os.environ["EXECUTOR_APPROVED_AUTH"],"binary":str(runtime/"native/bin/codex"),"interpreter":python,"hollywoodUrl":"http://127.0.0.1:18772","hostId":host,"model":"gpt-6.1-sol","effort":"xhigh"})
  saved(root/"global-provision-receipt.json",g)
  call("Owner","POST","placements",{"hostId":host,"name":"Private executor host","identityFingerprint":hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest(),"capabilities":{"liveness":True},"agentId":g["agentId"]})
  enrolled=enroll({"authorityId":a,"hostId":host,"hollywoodUrl":"http://127.0.0.1:18772","administratorCredential":people["Owner"],"policy":{"maxConcurrent":1,"reservedInteractive":0,"controlAgentIds":[g["agentId"]],"memoryPerTurnBytes":1024**2,"reserveMemoryBytes":4*1024**3,"sampleMaxAgeSeconds":30,"connectorMaxAgeSeconds":30}})
  saved(root/"host-enrollment.json",enrolled);config=json.loads(Path(enrolled["configPath"]).read_text());supervise(config,once=True)
  import secrets
  beta=str(uuid4());people["Beta"]={"principalId":beta,"token":secrets.token_urlsafe(40)}
  call("Owner","POST","principals",{"id":beta,"name":"Metadata waiting peer","kind":"agent","enrollmentCredential":people["Beta"]["token"]})
  call("Owner","PUT","rooms/"+room+"/membership",{"principalId":beta,"can_read":True,"can_post":True,"can_request":True,"revision":0})
  call("Owner","POST","placements",{"hostId":host,"name":"Private executor host","identityFingerprint":hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest(),"capabilities":{"liveness":True},"agentId":beta})
  source=call("Owner","POST","rooms/"+room+"/messages",{"operationId":"executor-source:"+str(uuid4()),"kind":"request","body":"Explicit metadata-only native resource qualification. No model task is admitted.","recipientId":g["agentId"]})
  saved(root/"original-request-receipt.json",source)
  claimed=call("Global","POST","connector/claim",{"operationId":"executor-claim:"+str(uuid4()),"hostId":host,"capabilities":CAPABILITIES});saved(root/"claim-receipt.json",claimed);d=claimed["delivery"];assert d
  pending=call("Owner","POST","rooms/"+room+"/messages",{"operationId":"executor-pending:"+str(uuid4()),"kind":"request","body":"Metadata admission check only. No agent model will run this request.","recipientId":beta})
  saved(root/"pending-receipt.json",pending)
  def beta_state():return call("Beta","POST","connector/observe",{"hostId":host,"capabilities":CAPABILITIES})
  assert beta_state()["reason"]=="host_capacity_exhausted"
  guardian=runtime/"qualification-resource-guardian.py";guardian.write_text(GUARDIAN);guardian.chmod(0o644)
  unit="lax-executor-proof-"+a.replace("-","")[:12]+".service"
  saved(root/"service-intent.json",{"unit":unit,"runtime":str(runtime),"nativeModelTurns":0})
  subprocess.run(["systemd-run","--unit="+unit,"--uid="+g["linuxUser"],"--property=KillMode=control-group","--property=UMask=0077","--property=MemoryMax=2G","--property=RuntimeMaxSec=180","--property=WorkingDirectory="+g["home"]+"/work",python,str(guardian),g["connectorConfig"],unit],capture_output=True,check=True)
  native_root=Path(g["home"])/"state/executor-qualification";wait(lambda:(native_root/"descriptor.json").exists())
  registration=register(a,host,g["agentId"],unit);saved(root/"service-registration.json",registration)
  descriptor=json.loads((native_root/"descriptor.json").read_text());executor=str(uuid4())
  body={"operationId":"executor-capture:"+str(uuid4()),"id":executor,"claimId":d["claim_id"],"generation":d["generation"],"hostId":host,**descriptor}
  saved(root/"capture-intent.json",{"deliveryId":d["id"],"payload":body})
  captured=call("Global","POST","connector/deliveries/"+d["id"]+"/executor",body);saved(root/"capture-receipt.json",captured)
  call("Global","POST","connector/deliveries/"+d["id"]+"/executor",{**body,"nativeStart":"0"},409)
  call("Beta","GET","executors/"+executor,status=403)
  checks.append("Captured original claim and exact process incarnation; changed capture and cross-agent read denied")
  supervise(config,once=True)
  live=call("Global","GET","executors/"+executor);assert live["executor"]["state"]=="live";saved(root/"live-receipt.json",live)
  assert beta_state()["reason"]=="host_capacity_exhausted"
  checks.append("Independent protected controller matches actual native executable/service and retains live capacity")
  call("Global","POST","hosts/"+host+"/executors/"+executor+"/observation",{"operationId":str(uuid4()),"machineIdentity":config["machineIdentity"],"descriptorDigest":live["executor"]["descriptor_digest"],"state":"live","evidence":live["executor"]["evidence"]},403)
  checks.append("Agent cannot impersonate enrolled host controller")
  flag("close-native");wait(lambda:(native_root/"native-closed.json").exists());supervise(config,once=True)
  held=call("Global","GET","executors/"+executor);assert held["executor"]["state"]=="unknown";assert held["executor"]["evidence"]["reason"]=="registered-unit-not-drained"
  assert held["executor"]["evidence"]["remainingWorkPids"];saved(root/"helper-held-receipt.json",held)
  assert beta_state()["reason"]=="host_capacity_exhausted"
  checks.append("Native exit alone does not release a group with a remaining actual helper")
  flag("stop-helper");wait(lambda:(native_root/"helper-stopped.json").exists());supervise(config,once=True)
  stopped=call("Global","GET","executors/"+executor);assert stopped["executor"]["state"]=="stopped"and stopped["deliveryState"]=="unknown"
  assert stopped["effectOutcomeNotInferredFromExecutor"]and stopped["stopDoesNotUndoExternalEffects"]
  eligible=beta_state();assert eligible["eligibleDeliveryId"]==pending["deliveries"][0]["id"]and eligible["capacity"]["active"]==0
  saved(root/"stopped-resource-receipt.json",stopped);saved(root/"unrelated-peer-admission.json",eligible)
  checks.append("Exact drained group releases physical occupancy while original delivery/effects stay unknown")
  assert call("Global","POST","connector/deliveries/"+d["id"]+"/executor",body)==captured
  supervise(config,once=True);assert call("Global","GET","executors/"+executor)==stopped
  checks.append("Capture receipt replay remains original and stopped observation is immutable/coalesced")
  call("Owner","POST","deliveries/"+pending["deliveries"][0]["id"]+"/cancel",{})
  flag("finish")
  result={"passed":True,"checks":checks,"actualNativeAppServer":True,"actualLinuxSystemdGroup":True,"providerInference":False,"nativeModelTurns":0,"unknownEffectsRetained":True,"unrelatedPeerSlotReleased":True,"originalGlobalControlJourneyQualified":False,"productionChanged":False,"physicalPhoneChanged":False}
  saved(root/"result.json",result);print(json.dumps(result),flush=True)
 finally:
  if unit:subprocess.run(["systemctl","stop",unit],capture_output=True)
  if api and api.poll()is None:api.terminate();api.wait(timeout=20)
  saved(root/"cleanup.json",{"ownedGuardianStopped":True,"ownedApiStopped":api is None or api.poll()is not None,"productionChanged":False})
  store.close()

if __name__=="__main__":main()
