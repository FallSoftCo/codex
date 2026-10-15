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
 if req.path=="/health":return web.json_response({"service":"owned-uncertain-control-fault"})
 body=await req.read();payload=json.loads(body)if body else {}
 original=json.loads((root/"lost-publication.json").read_text())if(root/"lost-publication.json").exists()else None
 if req.method=="GET"and original and req.path.endswith("/commands/"+original["operationId"])and not(root/"allow-receipt-read").exists():
  return web.json_response({"error":"Owned qualification holds the original publication receipt"},status=503)
 async with ClientSession()as session:
  async with session.request(req.method,"http://127.0.0.1:18772"+req.path_qs,data=body,headers={k:v for k,v in req.headers.items()if k.lower()in("authorization","content-type")},allow_redirects=False)as response:
   data=await response.read()
   drop=req.method=="POST"and req.path.endswith("/messages")and payload.get("kind")=="message"and "UNCERTAIN_STOP_CHECKPOINT"in payload.get("body","")and response.status==200 and not(root/"lost-publication.json").exists()
   stopping=req.method=="POST"and req.path.endswith("/state")and payload.get("state")=="cancelled"and response.status==200
   trace.append({"method":req.method,"path":req.path,"upstream":response.status,"ackDropped":drop,"goalStopAccepted":stopping});(root/"proxy-trace.json").write_text(json.dumps(trace))
   if stopping:(root/"allow-receipt-read").write_text("Original stop accepted; receipt reads resume")
   if drop:
    (root/"lost-publication.json").write_text(json.dumps({"operationId":payload["operationId"]}))
    return web.json_response({"error":"Owned qualification lost accepted publication acknowledgement"},status=503)
   return web.Response(body=data,status=response.status,content_type="application/json")
app=web.Application();app.router.add_route("*","/{tail:.*}",forward)
web.run_app(app,host="127.0.0.1",port=18773,print=None)
"""
LOCAL_CALLBACK_FAULT="""
import json,sys
from pathlib import Path
import lax_connector.connector as module
from lax_connector.journal import saved
original=module.Connector._tool
async def observe(self,method,params):
 if method=="item/tool/call"and params.get("tool")=="hollywood_goal_state":
  args=json.loads(params["arguments"])if isinstance(params["arguments"],str)else params["arguments"]
  if args.get("state")=="cancelled":
   saved(self.state/"qualification-uncertain-stop.json",{"priorEffectUnconfirmed":self.uncertain_tools,"tool":params["tool"],"callId":params["callId"]})
 return await original(self,method,params)
module.Connector._tool=observe
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
  task=("Run one finite cancellation-under-uncertainty check. Create one fresh engineer and Engineering room, set its home work role, and provision its separate non-sudo Linux execution. Create one goal titled Uncertain control, objective Prove that an authorised goal stop remains available while another original effect is uncertain, acceptance The worker command is stopped before forbidden-control-effect.txt is written and the goal becomes cancelled; set reviewBudget=0. Add and assign one work: read briefing, run one foreground shell command that writes ready to control-ready.txt then sleeps 45 seconds then writes forbidden to forbidden-control-effect.txt. Do not background it, submit completion or start other work. As Global, use one bounded shell wait of at most 60 seconds for control-ready.txt in the worker workspace returned by provisioning. Then call hollywood_publish with body UNCERTAIN_STOP_CHECKPOINT. Its reply will be unconfirmed; never resend it. Even while that publication remains uncertain, read the current goal revision and use hollywood_goal_state with state cancelled to stop that exact goal. Do not use shell/systemctl to cancel. Finish after the stop request without polling model turns or starting a review. Keep the ongoing Global role active. Do not touch old workers or schedules.")
  api("rooms/"+room+"/messages",{"operationId":"native-command:"+str(uuid4()),"kind":"request","body":task,"recipientId":glob["principalId"],"audience":"room"},"original-request")
  wait(lambda:(root/"lost-publication.json").exists(),360)
  def settled():
   s=state()
   return s if len(s["goals"])==1 and s["goals"][0]["state"]=="cancelled"and len(s["deliveries"])==2 and sorted(d["state"]for d in s["deliveries"])==["cancelled","completed"]else None
  completed=wait(settled,180)
  current=workers();assert len(current)==1
  worker=current[0];workspace=Path(worker["workspace"])
  assert(workspace/"control-ready.txt").exists()and not(workspace/"forbidden-control-effect.txt").exists()
  witness=json.loads((Path(g["home"])/"state/qualification-uncertain-stop.json").read_text());assert witness["priorEffectUnconfirmed"]
  tools=[json.loads(f.read_text())for f in(Path(g["home"])/"state").glob("tool-*.json")]
  assert any(t["tool"]=="hollywood_publish"and t.get("effectReconciled")for t in tools)
  assert any(t["tool"]=="hollywood_goal_state"and t["state"]=="completed"and t["result"]["success"]for t in tools)
  trace=json.loads((root/"proxy-trace.json").read_text());assert sum(1 for x in trace if x["ackDropped"])==1
  assert sum(1 for x in trace if x.get("goalStopAccepted"))==1
  result={"passed":True,"actualNativeTurns":2,"controlAdmittedWhilePriorEffectUnconfirmed":True,"goalStopAccepted":True,"workerCancelledBeforeDeferredEffect":True,"publicationOriginalReceiptRecoveredWithoutRepeat":True,"actualState":completed,"productionChanged":False,"physicalPhoneChanged":False}
  saved(root/"result.json",result);print(json.dumps(result),flush=True)
 finally:
  for w in workers():subprocess.run(["systemctl","disable","--now",w["unit"]],capture_output=True)
  if unit:subprocess.run(["systemctl","stop",unit],capture_output=True)
  for child in reversed(children):stop(child)
  saved(root/"cleanup.json",{"ownedChildrenStopped":all(p.poll()is not None for p in children),"ownedGlobalStopped":True,"ownedWorkersStoppedDisabled":True,"productionChanged":False})
  store.close()

if __name__=="__main__":main()
