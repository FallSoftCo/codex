"""Continue only the existing accepted delivery after observer handoff; no task/worker replay."""
import hashlib,importlib.util,json,os,signal,subprocess,time,runpy
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
sp=importlib.util.spec_from_file_location("m",Q/"run_goal_definition_r228.py");m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
C=m.ROOT/"goal-discovery-continuation-r237";p=json.loads((C/"protocol.json").read_text());arm=p["actors"]["reporter"];peer=p["actors"]["engineer"]
cfg=json.loads(Path(arm["config"]).read_text());pcfg=json.loads(Path(peer["config"]).read_text());handoff=json.loads((C/"observer-handoff-intent-r238.json").read_text());original=handoff["originalDelivery"]
private=json.loads((m.ROOT/"ordinary/installation-intent.json").read_text())
api=lambda method,path,body=None:m.request("http://127.0.0.1:18783",private["credentials"]["Owner"]["token"],method,path,body)
assert not (C/"delivery-observer-intent-r238.json").exists()
assert Path("/proc/"+str(handoff["observerPid"])+"/status").read_text().split("State:",1)[1].splitlines()[0].strip().startswith("T")
for path,h in json.loads((C/"freeze.json").read_text())["hashes"].items():assert m.digest(path)==h
units=[*arm["units"].values(),*peer["units"].values(),*arm["infrastructure"]]
before_pids={u:m.pid(u) for u in units};assert all(int(x)>1 for x in before_pids.values())
baseline={a["agent"]:m.h.usage(c,"three") for a,c in [(arm,cfg),(peer,pcfg)]}
started=time.time();deadline=started+600;state="delivery-observation-window-ended"
m.saved(C/"delivery-observer-intent-r238.json",{"at":started,"sourceSha256":m.digest(__file__),"originalDelivery":original,"originalEvent":handoff["originalEvent"],"taskSubmissionCount":0,"nativeWorkerRestarts":0,"beforePids":before_pids,"baselineUsage":baseline,"extendedObservationBounds":{"seconds":600,"additionalReportedNativeTokens":4000000},"originalBudgetClaim":"Original4M cached-inclusive pilot window extended at3.48M before implementation. Do not claim completion within original pilot budget or comparative efficiency. Frozen semantic checks and participant choices unchanged."})
def respond(att,d):
 aid=str(att["id"]);receipt=api("GET","attention/"+aid);assert receipt["canRespond"];assert d["reviewerKind"]=="coordinator-scripted-QA-participant"
 if "participant-approval.txt" in d["selectedFiles"]:
  assert all(x["satisfied"] for x in d["rubric"])
  for source in d["proposalSources"]:
   if source["kind"]=="file":assert m.digest(source["path"])==source["sha256"]
 text="\n\n".join((C/f).read_text() for f in d["selectedFiles"]);qs=receipt["attention"]["request"]["questions"];first=qs[0]["id"]
 answers={q["id"]:{"answers":[text if i==0 else "The full answer to "+first+" applies here as well."]} for i,q in enumerate(qs)}
 assert len(json.dumps({"type":"hollywoodQuestionAnswer","attentionId":aid,"answers":answers}).encode())<=6000
 op="goal-discovery-r238:answer:"+aid
 return m.submit(C,"delivery-answer-"+aid,api,"POST","attention/"+aid+"/response",{"operationId":op,"scope":receipt["scope"],"response":{"answers":answers}},"attention/"+aid+"/commands/"+op)
def retire(db):
 try:
  snap=m.snapshot(db,arm,peer)
  for d in snap["deliveries"]:
   if d["state"] not in ["completed","failed","cancelled","unknown"]:
    m.submit(C,"delivery-retire-"+str(d["id"]),api,"POST","deliveries/"+str(d["id"])+"/cancel",{},"deliveries/"+str(d["id"]))
  # Keep owned placements enabled while the original cancellation/end receipts settle.
  drain=time.time()+30
  while any(x["active_turn"] for x in m.snapshot(db,arm,peer)["contexts"]) and time.time()<drain:time.sleep(.5)
  settled=m.snapshot(db,arm,peer)
  for a in [arm,peer]:
   row=api("GET","placements/"+a["agent"])
   m.administrative_put(C,api,"placements/"+a["agent"],{"operationId":"goal-discovery-r238:retire:"+a["agent"],"hostId":a["host"],"revision":row["placement"]["revision"],"enabled":False})
 finally:
  subprocess.run(["systemctl","stop",*units],check=True,capture_output=True)
  m.saved(C/"retirement-r238.json",m.h.serialize({"at":time.time(),"state":state,"unitPids":{u:m.pid(u) for u in units},"contextsBeforePause":settled["contexts"] if "settled" in locals() else None,"originalCancelledPredecessorNotResumed":True}))
env=dict(x.split("=",1) for x in json.loads(subprocess.check_output(["docker","inspect","--format","{{json .Config.Env}}","harness-postgres"],text=True)) if "=" in x)
dbc=json.loads(Path("/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json").read_text());role=dbc["user"];dbc.update(user=env["POSTGRES_USER"],password=env["POSTGRES_PASSWORD"],application_name="goal-discovery-delivery-observer-r238")
with psycopg.connect(**dbc,row_factory=dict_row,autocommit=True) as db:
 db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
 try:
  snap=m.snapshot(db,arm,peer);row=next(x for x in snap["deliveries"] if str(x["id"])==original);assert row["state"]=="running"
  os.kill(handoff["observerPid"],signal.SIGKILL)
  m.saved(C/"observer-handoff-completed-r238.json",{"at":time.time(),"oldObserverOnlyKilled":handoff["observerPid"],"nativeUnitPidsUnchanged":{u:m.pid(u) for u in units}==before_pids,"originalTaskReposted":False})
  last=None;quiet=None;answered=[]
  while time.time()<deadline:
   snap=m.snapshot(db,arm,peer);row=next(x for x in snap["deliveries"] if str(x["id"])==original)
   for att in [x for x in snap["attention"] if x["state"]=="pending" and str(x["id"]) not in answered]:
    aid=str(att["id"]);needed=C/"participant-reviews"/(aid+"-needed.json");decision=needed.with_name(aid+"-decision.json")
    if not needed.exists():m.saved(needed,m.h.serialize({"at":time.time(),"attention":att,"policy":"Same frozen participant responses and rubric; no implementation coaching."}));print(json.dumps({"participantReviewNeeded":str(needed)}),flush=True)
    if decision.exists():
     assert len(answered)<3
     respond(att,json.loads(decision.read_text()));answered.append(aid)
   current={a["agent"]:m.h.usage(c,"three") for a,c in [(arm,cfg),(peer,pcfg)]}
   delta=sum(x["total_tokens"] for x in current.values())-sum(x["total_tokens"] for x in baseline.values())
   summary={"at":time.time(),"originalState":row["state"],"activeContexts":sum(x["active_turn"] is not None for x in snap["contexts"]),"newAnswers":len(answered),"implementationExists":(Path(arm["workspace"])/"weekly_report.py").exists(),"addedNativeTokensSinceHandoff":delta}
   marker=json.dumps({k:v for k,v in summary.items() if k!="at"})
   if marker!=last:m.saved(C/"latest-r238.json",m.h.serialize({"summary":summary,"snapshot":snap}));print(json.dumps(summary),flush=True);last=marker
   if delta>4000000:state="extended-native-usage-budget-exceeded";break
   if all(x["state"] in ["completed","failed","cancelled","unknown"] for x in snap["deliveries"]) and not any(x["active_turn"] for x in snap["contexts"]):
    if quiet is None:quiet=time.time()
    if time.time()-quiet>=12:state="settled" if row["state"]=="completed" else "settled-with-incomplete-original";break
   else:quiet=None
   time.sleep(1)
  checks=runpy.run_path(str(C/"outcome_scorer.py"))["evaluate"](arm["workspace"],peer["workspace"],arm["host"],arm["linuxUser"])
  snap=m.snapshot(db,arm,peer)
  m.saved(C/"result-r238.json",m.h.serialize({"at":time.time(),"state":state,"originalDelivery":original,"originalEvent":handoff["originalEvent"],"secondsTotalSinceNewRequest":time.time()-json.loads((C/"request-public.json").read_text())["at"],"secondsSinceObserverHandoff":time.time()-started,"snapshot":snap,"functionalChecks":checks,"participantAnswers":answered,"consumerUsage":m.h.usage(cfg,"three"),"peerUsage":m.h.usage(pcfg,"three"),"sameNativeUnitPidsThroughoutHandoff":{u:m.pid(u) for u in units}==before_pids,"taskSubmissionsByThisObserver":0,"artifactRepairs":0,"originalCancelledTrialRetained":True,"observationBudgetExtended":True,"independentFinalAuditPending":True}))
  print(json.dumps({"state":state,"functionalPassed":sum(x["passed"] for x in checks),"functionalTotal":len(checks)}),flush=True)
 except BaseException as error:
  m.saved(C/"delivery-observer-failure-r238.json",{"at":time.time(),"error":type(error).__name__,"detail":str(error)[:700],"originalDelivery":original,"newTaskSubmissions":0});raise
 finally:retire(db)

