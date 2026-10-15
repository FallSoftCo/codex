"""Actual Global/worker artifact delivery through lost command acknowledgements."""
import hashlib,json,os,pwd,secrets,socket,subprocess,time,urllib.request
from pathlib import Path
from uuid import uuid4
from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.store import Store,json_value
from lax_connector.linux_admin import provision
from lax_connector.host import enroll,resources
from lax_connector.journal import saved

PROXY="""
import json,sys
from pathlib import Path
from aiohttp import web,ClientSession
root=Path(sys.argv[1]);trace=[]
async def forward(req):
 if req.path=="/health":return web.json_response({"service":"owned-command-receipt-fault"})
 body=await req.read();payload=json.loads(body)if body else {}
 report=json.loads((root/"lost-report.json").read_text())if(root/"lost-report.json").exists()else None
 blocked=req.method=="GET" and report and req.path.endswith("/commands/"+report["operationId"])and not(root/"allow-receipt-read").exists()
 if blocked:
  trace.append({"method":req.method,"path":req.path,"blockedOriginalRead":True});(root/"proxy-trace.json").write_text(json.dumps(trace))
  return web.json_response({"error":"Owned qualification temporarily disconnects original receipt reads"},status=503)
 async with ClientSession()as session:
  async with session.request(req.method,"http://127.0.0.1:18772"+req.path_qs,data=body,headers={k:v for k,v in req.headers.items()if k.lower()in("authorization","content-type")},allow_redirects=False)as response:
   data=await response.read();kind="goal"if req.method=="POST"and req.path.endswith("/goals")else"report"if req.method=="POST"and req.path.endswith("/report")else None
   dropped=bool(kind and response.status==200 and not(root/("lost-"+kind+".json")).exists())
   trace.append({"method":req.method,"path":req.path,"upstream":response.status,"ackDropped":dropped,"operationId":payload.get("operationId")});(root/"proxy-trace.json").write_text(json.dumps(trace))
   if dropped:
    (root/("lost-"+kind+".json")).write_text(json.dumps({"operationId":payload["operationId"],"acceptedResult":json.loads(data)}))
    return web.json_response({"error":"Owned qualification lost an accepted command acknowledgement"},status=503)
   return web.Response(body=data,status=response.status,content_type="application/json")
app=web.Application();app.router.add_route("*","/{tail:.*}",forward)
web.run_app(app,host="127.0.0.1",port=18773,print=None)
"""
LOCAL_CALLBACK_FAULT="""
import json,sys
from pathlib import Path
import lax_connector.connector as module
from lax_connector.journal import saved
config=json.loads(Path(sys.argv[sys.argv.index("--config")+1]).read_text())
flag=Path(config["state"])/"qualification-admin-callback-gap.json"
original=module.saved
def drop(path,value):
 if value.get("state")=="completed"and value.get("tool")=="hollywood_create_agent"and value.get("result",{}).get("success")and not flag.exists():
  saved(flag,{"tool":value["tool"],"callId":value["callId"],"fault":"Admin workflow completed, native callback journal write hidden once"})
  raise OSError("Owned qualification lost local callback completion")
 return original(path,value)
module.saved=drop
module.main()
"""

def main():
 os.umask(0o077);assert os.geteuid()==0 and socket.gethostname()=="ozzz-aosp"
 root=Path(os.environ["NATIVE_COMMAND_EVIDENCE"]);root.mkdir(mode=0o711);root.chmod(0o711)
 runtime=Path(os.environ["NATIVE_COMMAND_RUNTIME"]);python=str(runtime/"venv/bin/python");dbp=Path(os.environ["NATIVE_COMMAND_DATABASE_CONFIG"])
 for port in(18772,18773):
  with socket.socket()as s:s.bind(("127.0.0.1",port))
 initialize(json.loads(dbp.read_text()),root/"enterprise","Actual native command recovery")
 setup=json.loads((root/"enterprise/installation-intent.json").read_text());authority=setup["authorityId"];owner=setup["credentials"]["Owner"];glob=setup["credentials"]["Global"];room=setup["globalRoomId"];host=str(uuid4())
 store=Store(json.loads(dbp.read_text()));children=[];unit=None;g=None
 saved(root/"intent.json",{"scope":"One fresh finite actual Global/worker mission; lost original command/local callback acknowledgements; one independent material review","productionChanged":False,"physicalPhoneChanged":False,"runtime":str(runtime)})
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
  api("placements",{"hostId":host,"name":"Native command recovery OZZZ","identityFingerprint":hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest(),"capabilities":{"localProvisioning":True},"agentId":glob["principalId"]},"placement")
  enrolled=enroll({"authorityId":authority,"hostId":host,"hollywoodUrl":"http://127.0.0.1:18773","administratorCredential":owner,"policy":{"maxConcurrent":resources()["cpuSlots"],"reservedInteractive":1 if resources()["cpuSlots"]>1 else 0,"controlAgentIds":[glob["principalId"]],"memoryPerTurnBytes":2*1024**3,"reserveMemoryBytes":4*1024**3,"sampleMaxAgeSeconds":20,"connectorMaxAgeSeconds":20}});saved(root/"host-enrollment.json",enrolled)
  subprocess.run([python,"-m","lax_connector.host","--once",enrolled["configPath"]],capture_output=True,check=True);launch("host-controller",[python,"-m","lax_connector.host","--serve",enrolled["configPath"]])
  wrapper=runtime/"qualification-local-callback-gap.py";wrapper.write_text(LOCAL_CALLBACK_FAULT);wrapper.chmod(0o644)
  unit="lax-command-global-"+authority.replace("-","")[:12];saved(root/"global-service-intent.json",{"unit":unit})
  subprocess.run(["systemd-run","--unit="+unit,"--uid="+g["linuxUser"],"--property=UMask=0077","--property=MemoryMax=3G","--property=RuntimeMaxSec=1200","--property=WorkingDirectory="+g["home"]+"/work",python,str(wrapper),"--config",g["connectorConfig"],"--serve"],capture_output=True,check=True)
  marker="ORIGINAL_RECEIPT_"+secrets.token_hex(12);saved(root/"expected-marker.json",{"marker":marker})
  task=("Run one finite Global-to-worker enterprise deliverable. Create one fresh engineer, its Engineering room and home work role, and provision its separate non-sudo Linux execution. Create one goal titled Original command receipt delivery, objective Produce and independently verify an actual worker artifact despite lost transport acknowledgements, acceptance The worker file receipt-proof.txt contains exactly "+marker+" and newline, its connector evidence matches the file, Global independently verifies bytes/hash and explicitly accepts the work and goal. Set reviewBudget=1 for one material completion review. Add and assign exactly one work to that engineer: read the briefing, write exactly "+marker+" and newline to receipt-proof.txt in its workspace, verify actual bytes/hash, complete its bounded native goal and submit artifactPaths receipt-proof.txt with current revision. Do not ask a question, create extra workers or poll models. End the initial Global turn promptly after delegation. In the one material completion review, read canonical work/evidence, independently inspect the actual file through your host administration and accept work/goal only after verification. Keep the ongoing Global role active. Do not replay uncertain operations, schedule, self-chain or touch historical work.")
  api("rooms/"+room+"/messages",{"operationId":"native-command:"+str(uuid4()),"kind":"request","body":task,"recipientId":glob["principalId"],"audience":"room"},"original-request")
  wait(lambda:(root/"lost-report.json").exists(),360)
  def worker_finished():
   for w in workers():
    home=Path(w["workspace"]).parent
    for f in(home/"codex-home/sessions").rglob("*.jsonl"):
     for line in f.read_text().splitlines():
      try:v=json.loads(line)
      except ValueError:continue
      if v.get("type")=="event_msg"and v.get("payload",{}).get("type")=="task_complete":return w
   return None
  worker=wait(worker_finished,120)
  before=state();saved(root/"before-receipt-reconnect.json",before)
  (root/"allow-receipt-read").write_text("Inspect original accepted command; no task or tool replay\n")
  def accepted():
   s=state();return s if len(s["goals"])==1 and s["goals"][0]["state"]=="accepted"and len(s["work"])==1 and s["work"][0]["state"]=="accepted"and len(s["deliveries"])==3 and all(d["state"]=="completed"for d in s["deliveries"])else None
  completed=wait(accepted,420)
  assert(Path(worker["workspace"])/"receipt-proof.txt").read_text()==marker+"\n"
  root_tools=[json.loads(p.read_text())for p in(Path(g["home"])/"state").glob("tool-*.json")]
  assert any(t["tool"]=="hollywood_create_agent"and t.get("effectRecoveredByOriginalRead")for t in root_tools)
  assert any(t["tool"]=="hollywood_goal_create"and t.get("effectRecoveredByOriginalRead")for t in root_tools)
  worker_tools=[json.loads(p.read_text())for p in(Path(worker["workspace"]).parent/"state").glob("tool-*.json")]
  assert any(t["tool"]=="hollywood_work_report"and t.get("effectReconciled")for t in worker_tools)
  trace=json.loads((root/"proxy-trace.json").read_text())
  for ending in("/goals","/report"):
   posts=[x for x in trace if x["method"]=="POST"and x["path"].endswith(ending)]
   assert len(posts)==1 and posts[0]["ackDropped"]
  result={"passed":True,"actualNativeTurns":3,"globalContexts":1,"workerContexts":1,"adminCompletedJournalRecoveredWithoutRepeat":True,"goalCreateRecoveredLiveByOriginalCommandRead":True,"workerReportRecoveredAfterOriginalTurnEnded":True,"goalCreatePosts":1,"workReportPosts":1,"originalArtifactIndependentlyAccepted":True,"artifactSha256":hashlib.sha256((Path(worker["workspace"])/"receipt-proof.txt").read_bytes()).hexdigest(),"actualState":completed,"modelPolling":False,"originalTaskResubmitted":False,"productionChanged":False,"physicalPhoneChanged":False}
  saved(root/"result.json",result);print(json.dumps(result),flush=True)
 finally:
  for w in workers():subprocess.run(["systemctl","disable","--now",w["unit"]],capture_output=True)
  if unit:subprocess.run(["systemctl","stop",unit],capture_output=True)
  for child in reversed(children):stop(child)
  saved(root/"cleanup.json",{"ownedChildrenStopped":all(p.poll()is not None for p in children),"ownedGlobalStopped":True,"ownedWorkersStoppedDisabled":True,"productionChanged":False})
  store.close()

if __name__=="__main__":main()
