"""Actual native Global/worker deliverable, current-turn steering and lost real acknowledgements."""
import hashlib,json,os,pwd,secrets,socket,subprocess,time,urllib.request,urllib.error
from pathlib import Path
from uuid import uuid4
from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.store import Store
from lax_connector.host import enroll,resources
from lax_connector.linux_admin import provision
from lax_connector.journal import saved

PROXY = """
import json,sys
from pathlib import Path
from aiohttp import web,ClientSession
root=Path(sys.argv[1]);trace=[]
async def forward(req):
 if req.path=="/health":return web.json_response({"service":"owned-native-steering-proxy"})
 body=await req.read()
 async with ClientSession() as session:
  async with session.request(req.method,"http://127.0.0.1:18772"+req.path_qs,data=body,headers={k:v for k,v in req.headers.items() if k.lower() in ("authorization","content-type")},allow_redirects=False) as response:
   data=await response.read()
   drop=req.method=="POST" and req.path.endswith("/guidance") and "/deliveries/" in req.path and "/connector/" not in req.path and response.status==200 and not (root/"lost-human-ack.json").exists()
   trace.append({"method":req.method,"path":req.path,"status":response.status,"ackDropped":drop});(root/"trace.json").write_text(json.dumps(trace))
   if drop:
    (root/"lost-human-ack.json").write_bytes(data)
    return web.json_response({"error":"Owned qualification dropped an accepted human guidance acknowledgement"},status=503)
   return web.Response(body=data,status=response.status,content_type="application/json")
app=web.Application();app.router.add_route("*","/{tail:.*}",forward)
web.run_app(app,host="127.0.0.1",port=18773,print=None)
"""
DROP_NATIVE_ACK = """
import json,sys
from pathlib import Path
from lax_connector.rpc import AppServer,RpcError
from lax_connector.connector import main
from lax_connector.journal import saved
config=json.loads(Path(sys.argv[sys.argv.index("--config")+1]).read_text())
path=Path(config["state"])/"qualification-lost-native-steer-ack.json"
original=AppServer.call
async def call(self,method,params,**kwargs):
 result=await original(self,method,params,**kwargs)
 if method=="turn/steer" and not path.exists():
  saved(path,{"method":method,"clientUserMessageId":params["clientUserMessageId"],"nativeReceipt":result,"fault":"Real native response received then intentionally hidden from connector"})
  raise RpcError("Owned qualification lost real native acknowledgement")
 return result
AppServer.call=call
main()
"""

def main():
 os.umask(0o077)
 assert os.geteuid()==0 and socket.gethostname()=="ozzz-aosp"
 root=Path(os.environ["STEERING_EVIDENCE"]);root.mkdir(mode=0o711);root.chmod(0o711)
 runtime=Path(os.environ["STEERING_RUNTIME"]);python=str(runtime/"venv/bin/python")
 dbpath=Path(os.environ["STEERING_DATABASE_CONFIG"]);db=json.loads(dbpath.read_text())
 repo=Path(os.environ["STEERING_NEXTCOMP"]);a=pwd.getpwnam("aosp")
 for port in (18772,18773,18888):
  with socket.socket() as s:s.bind(("127.0.0.1",port))
 initialize(db,root/"enterprise","Real native steering qualification")
 setup=json.loads((root/"enterprise/installation-intent.json").read_text())
 owner=setup["credentials"]["Owner"];glob=setup["credentials"]["Global"];authority=setup["authorityId"];room=setup["globalRoomId"];host=str(uuid4())
 saved(root/"intent.json",{"scope":"Fresh finite actual Global/worker deliverable, one human steer, lost actual acknowledgements and explicit native stop","productionChanged":False,"physicalPhone":False,"runtime":str(runtime)})
 saved(Path("/opt/hetzner-blue-team/coordination/announcements")/("native-steering-"+authority+".json"),{"owner":"01a12c58-d21a-79b0-a512-0c3bc6dc0ee4","host":"ozzz-aosp","privateListeners":["127.0.0.1:18772","127.0.0.1:18773","127.0.0.1:18888"],"scope":"Fresh finite native Global/worker plus authenticated NextComp gateway; no old owners","credentials":str(root/"enterprise/installation-intent.json"),"rollback":"Stop only owned API/proxy/gateway/controller and this authority Global/worker units"})
 children=[];global_receipt=None;unit=None;store=Store(db)
 def launch(name,args,user=None,env=None,cwd=None):
  with (root/(name+".log")).open("ab") as f:
   p=subprocess.Popen((["runuser","-u",user,"--"]if user else [])+args,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,env=env,cwd=cwd)
  children.append(p);saved(root/(name+"-process.json"),{"pid":p.pid});return p
 def stop(p):
  if p and p.poll() is None:p.terminate();p.wait(timeout=20)
 def ready(base,p):
  for _ in range(100):
   assert p.poll() is None,"Owned service stopped before health"
   try:
    with urllib.request.urlopen(base+"/health",timeout=2) as res:
     if res.status==200:return
   except OSError:time.sleep(.25)
  raise RuntimeError("Owned service health timed out")
 def call(base,path,body=None,token=None,binding=None,status=200,name=None,method=None):
  if body is not None:
   assert name
   saved(root/(name+"-intent.json"),{"path":path,"body":body})
  req=urllib.request.Request(base+path,method=method or ("POST"if body is not None else "GET"),data=None if body is None else json.dumps(body).encode(),headers={"Content-Type":"application/json",**({"Authorization":"Bearer "+token}if token else {}),**({"X-Hollywood-Binding":binding}if binding else {})})
  try:
   with urllib.request.urlopen(req,timeout=15) as res:code=res.status;value=json.load(res)
  except urllib.error.HTTPError as error:code=error.code;value=json.load(error)
  assert code==status,(path,code,value,status)
  if name:saved(root/(name+"-receipt.json"),{"status":code,"value":value})
  return value
 def api(path,body=None,name=None,method=None,status=200):
  return call("http://127.0.0.1:18772","/hollywood/v3/"+path,body,owner["token"],name=name,method=method,status=status)
 def workers():
  return [json.loads(p.read_text())for p in (Path("/var/lib/harness")/authority/"workers").glob("*/provision-receipt.json")]
 def state():
  with store.pool.connection() as c:
   goals=c.execute("SELECT id,state FROM hb_goal WHERE authority=%s",(authority,)).fetchall()
   work=c.execute("SELECT id,state,evidence,owner FROM hb_work WHERE authority=%s",(authority,)).fetchall()
   deliveries=c.execute("SELECT id,agent,state,native_thread,native_turn FROM hb_delivery WHERE authority=%s ORDER BY updated_at",(authority,)).fetchall()
  return {"goals":[{k:str(v) if k=="id"else v for k,v in row.items()}for row in goals],"work":[{k:str(v)if k in ("id","owner")else v for k,v in row.items()}for row in work],"deliveries":[{k:str(v) if k in ("id","agent")else v for k,v in row.items()}for row in deliveries]}
 def wait(test,seconds=180):
  deadline=time.monotonic()+seconds
  while time.monotonic()<deadline:
   value=test()
   if value:return value
   time.sleep(.5)
  saved(root/"timeout-state.json",state());raise RuntimeError("Finite native steering condition timed out")
 try:
  api_process=launch("api",[python,"-m","hollywood_backbone.server","--database-config",str(dbpath),"--port","18772"]);ready("http://127.0.0.1:18772",api_process)
  proxy=root/"proxy.py";proxy.write_text(PROXY)
  proxy_process=launch("proxy",[python,str(proxy),str(root)]);ready("http://127.0.0.1:18773",proxy_process)
  data=root/"gateway-data";data.mkdir(mode=0o700);os.chown(data,a.pw_uid,a.pw_gid)
  config={"format":"hollywood-nextcomp-binding/v1","installationId":str(uuid4()),"devices":{"owner":{"url":"http://127.0.0.1:18773","tokenFile":str(data/"human.key"),"authorityId":authority,"principalId":owner["principalId"],"defaultRoomId":room}}}
  bootstrap="import{readFileSync,writeFileSync}from'node:fs';import{openStore}from'"+(repo/"server/store.mjs").as_uri()+"';const s=JSON.parse(readFileSync(0,'utf8'));const{db,secrets}=openStore(s.data);db.close();writeFileSync(s.data+'/human.key',s.token,{mode:0o600});writeFileSync(s.data+'/hollywood.json',JSON.stringify(s.config),{mode:0o600});console.log(JSON.stringify({adminToken:secrets.adminToken}));"
  seeded=subprocess.run(["runuser","-u","aosp","--","node","--input-type=module","-e",bootstrap],input=json.dumps({"data":str(data),"token":owner["token"],"config":config}),capture_output=True,text=True,cwd=repo)
  (root/"gateway-bootstrap.stderr").write_text(seeded.stderr);seeded.check_returncode();admin=json.loads(seeded.stdout)["adminToken"]
  env={**os.environ,"PORT":"18888","POCKET_DATA":str(data),"POCKET_EXECUTION_BACKEND":"hollywood","CODEX_SOCKET":str(root/"no-stock-runtime.sock"),"POCKET_CODEX_COMMAND":""}
  gateway=launch("gateway-bootstrap",["node",str(repo/"server/index.mjs")],user="aosp",env=env,cwd=repo);ready("http://127.0.0.1:18888",gateway)
  pairing=call("http://127.0.0.1:18888","/api/pairing",{},admin,name="pairing-code")
  paired=call("http://127.0.0.1:18888","/api/pair",{"code":pairing["code"],"name":"Native steering qualification"},name="pairing")
  stop(gateway);config["devices"][paired["id"]]=config["devices"]["owner"];(data/"hollywood.json").write_text(json.dumps(config));os.chown(data/"hollywood.json",a.pw_uid,a.pw_gid)
  gateway=launch("gateway",["node",str(repo/"server/index.mjs")],user="aosp",env=env,cwd=repo);ready("http://127.0.0.1:18888",gateway)
  identity=call("http://127.0.0.1:18888","/api/hollywood/v3/identity",token=paired["token"])
  def phone(path,body=None,name=None,status=200):
   return call("http://127.0.0.1:18888","/api/hollywood/v3/"+path,body,paired["token"],identity["bindingId"],status=status,name=name)
  global_receipt=provision({"installationIntent":str(root/"enterprise/installation-intent.json"),"approvedModelAuthFile":os.environ["STEERING_APPROVED_AUTH"],"binary":str(runtime/"native/bin/codex"),"interpreter":python,"hollywoodUrl":"http://127.0.0.1:18772","hostId":host,"model":"gpt-6.1-sol","effort":"xhigh"})
  saved(root/"global-provision-receipt.json",global_receipt)
  api("placements",{"hostId":host,"name":"Native steering OZZZ","identityFingerprint":hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest(),"capabilities":{"localProvisioning":True},"agentId":glob["principalId"]},"placement")
  enrolled=enroll({"authorityId":authority,"hostId":host,"hollywoodUrl":"http://127.0.0.1:18772","administratorCredential":owner,"policy":{"maxConcurrent":resources()["cpuSlots"],"reservedInteractive":1 if resources()["cpuSlots"]>1 else 0,"controlAgentIds":[glob["principalId"]],"memoryPerTurnBytes":2*1024**3,"reserveMemoryBytes":4*1024**3,"sampleMaxAgeSeconds":20,"connectorMaxAgeSeconds":20}})
  saved(root/"host-enrollment.json",enrolled)
  subprocess.run([python,"-m","lax_connector.host","--once",enrolled["configPath"]],check=True,capture_output=True)
  launch("host-controller",[python,"-m","lax_connector.host","--serve",enrolled["configPath"]])
  wrapper=runtime/"qualification-drop-steer-ack.py"
  if wrapper.exists():assert wrapper.read_text()==DROP_NATIVE_ACK
  else:wrapper.write_text(DROP_NATIVE_ACK);wrapper.chmod(0o644)
  unit="lax-steering-global-"+authority.replace("-","")[:12]
  saved(root/"global-service-intent.json",{"unit":unit})
  subprocess.run(["systemd-run","--unit="+unit,"--uid="+global_receipt["linuxUser"],"--property=UMask=0077","--property=MemoryMax=3G","--property=RuntimeMaxSec=1100","--property=WorkingDirectory="+global_receipt["home"]+"/work",python,str(wrapper),"--config",global_receipt["connectorConfig"],"--serve"],check=True,capture_output=True)
  request=("Run one finite Global-to-worker artifact deliverable. First read hollywood_briefing, then run one command that writes ready followed by newline to steering-ready.txt in your workspace and sleeps 35 seconds. This bounded command gives the human time to send guidance to this same turn. After that command, use the marker supplied by the human guidance; do not infer or invent it. Create one new engineer, its Engineering room and home work role; provision that separate non-sudo Linux worker. Create one goal titled Native steering artifact, objective Deliver the exact human-guided marker through a separately executed worker and independently verify it, acceptance A worker artifact steering-proof.txt contains exactly the guidance marker and newline, Global independently reads the file and checks its hash, then accepts work and goal. Set reviewBudget=1 for one material completion review. Create and assign one work to that engineer, instructing it to write the actual supplied marker and newline to steering-proof.txt, verify it, finish its native goal and submit artifactPaths steering-proof.txt with connector-hashed evidence and current revision. Do not ask a question, poll models or create extra workers. End your initial turn after delegation. In the one completion review, inspect the canonical work evidence and actual artifact through your host administration, accept work and goal only after verifying the exact marker and hash, and keep your native role active. Do not restart any historical service or schedule.")
  submitted=phone("rooms/"+room+"/messages",{"operationId":"steering-task:"+str(uuid4()),"kind":"request","body":request,"recipientId":glob["principalId"],"audience":"room"},name="original-request")
  original=submitted["deliveries"][0]["id"]
  ready_file=Path(global_receipt["home"])/"work/steering-ready.txt"
  wait(lambda:ready_file.exists(),180)
  metadata=phone("rooms/"+room);active=next(d for d in metadata["deliveries"]if d["id"]==original)
  assert active["can_steer"];scope=active["control_scope"]
  marker="STEERRED_"+secrets.token_hex(12)
  guidance={"id":str(uuid4()),"operationId":"guidance:"+str(uuid4()),"scope":scope,"body":"For the current deliverable, the exact marker is "+marker+". Apply it to the one worker assignment and independently verify it before acceptance. Continue the existing task in this original execution."}
  saved(root/"expected-marker.json",{"marker":marker})
  phone("deliveries/"+original+"/guidance",guidance,name="human-guidance",status=503)
  stop(api_process)
  api_process=launch("api-restarted",[python,"-m","hollywood_backbone.server","--database-config",str(dbpath),"--port","18772"]);ready("http://127.0.0.1:18772",api_process)
  receipt=phone("native-controls/"+guidance["id"],name="original-guidance-after-restart")
  assert receipt["control"]["id"]==guidance["id"] and receipt["control"]["body"]==guidance["body"]
  def accepted():
   snap=state()
   return snap if snap["goals"] and all(g["state"]=="accepted"for g in snap["goals"]) and all(w["state"]=="accepted"for w in snap["work"]) and len(snap["deliveries"])==3 and all(d["state"]=="completed"for d in snap["deliveries"])else None
  completed=wait(accepted,540)
  receipt=wait(lambda:(v if (v:=phone("native-controls/"+guidance["id"]))["control"]["state"]=="native_recorded"else None),30)
  assert receipt["scope"]==scope and not receipt["modelConsumptionProved"]
  receipts=workers();assert len(receipts)==1
  worker=receipts[0];artifact=Path(worker["workspace"])/"steering-proof.txt"
  assert artifact.read_text()==marker+"\n"
  native_fault=Path(global_receipt["home"])/"state/qualification-lost-native-steer-ack.json";assert native_fault.exists()
  fault=json.loads(native_fault.read_text());assert fault["nativeReceipt"]["turnId"]==scope["nativeTurn"]
  proxy_trace=json.loads((root/"trace.json").read_text());posts=[x for x in proxy_trace if x["method"]=="POST"and x["path"].endswith("/guidance")]
  assert len(posts)==1 and posts[0]["ackDropped"]
  saved(root/"accepted-deliverable.json",completed)
  # A separate explicit human request proves Stop while retaining this Global role.
  cancel_body="Run only this bounded cancellation check. Execute one shell command that writes ready to cancel-ready.txt, sleeps 45 seconds and then writes forbidden to forbidden-steering-effect.txt. Do not spawn background jobs or other agents. The human will cancel this work while its command is active."
  cancel=phone("rooms/"+room+"/messages",{"operationId":"cancel-task:"+str(uuid4()),"kind":"request","body":cancel_body,"recipientId":glob["principalId"],"audience":"room"},name="cancel-request")
  cancel_id=cancel["deliveries"][0]["id"];wait(lambda:(Path(global_receipt["home"])/"work/cancel-ready.txt").exists(),180)
  started=time.monotonic();phone("deliveries/"+cancel_id+"/cancel",{},name="cancel-original")
  stopped=wait(lambda:(v if (v:=phone("deliveries/"+cancel_id))["delivery"]["state"]=="cancelled"else None),40)
  stop_latency=time.monotonic()-started
  assert not (Path(global_receipt["home"])/"work/forbidden-steering-effect.txt").exists()
  final=state();assert len(final["deliveries"])==4
  assert next(d for d in final["deliveries"]if d["id"]==original)["native_turn"]==scope["nativeTurn"]
  result={"passed":True,"actualNativeTurns":4,"nativePointersSynthetic":False,"guidanceOriginalNativeTurn":scope["nativeTurn"],"guidanceControlId":guidance["id"],"nativeGuidanceState":receipt["control"]["state"],"humanGuidancePosts":len(posts),"lostHumanAckRecoveredByOriginalGet":True,"lostActualNativeAckRecoveredByOriginalMessage":True,"sameOriginalDelivery":True,"artifact":{"path":str(artifact),"sha256":hashlib.sha256(artifact.read_bytes()).hexdigest()},"goalAndWorkAccepted":True,"stopState":stopped["delivery"]["state"],"stopLatencySeconds":stop_latency,"deferredStopEffectAbsent":True,"productionChanged":False,"physicalPhoneChanged":False,"androidUIExercised":False}
  saved(root/"result.json",result);print(json.dumps(result),flush=True)
 finally:
  if unit:subprocess.run(["systemctl","stop",unit],capture_output=True)
  for worker in workers():subprocess.run(["systemctl","disable","--now",worker["unit"]],capture_output=True)
  for child in reversed(children):stop(child)
  saved(root/"cleanup.json",{"ownedChildrenStopped":all(p.poll()is not None for p in children),"workersStoppedDisabled":True,"globalStopped":True,"productionChanged":False})
  store.close()

if __name__=="__main__":main()
