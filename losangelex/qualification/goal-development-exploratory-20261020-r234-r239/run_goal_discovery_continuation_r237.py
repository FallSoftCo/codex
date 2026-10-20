"""One bounded native discovery journey. Never replay original requests or peer tasks."""
import importlib.util,json,subprocess,time,hashlib,runpy
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
sp=importlib.util.spec_from_file_location("prior",Q/"run_goal_definition_r228.py")
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
C=m.ROOT/"goal-discovery-continuation-r237"
p=json.loads((C/"protocol.json").read_text());frozen=json.loads((C/"freeze.json").read_text())
arm=p["actors"]["reporter"];peer=p["actors"]["engineer"]
cfg=json.loads(Path(arm["config"]).read_text());pcfg=json.loads(Path(peer["config"]).read_text())
private=json.loads((m.ROOT/"ordinary/installation-intent.json").read_text())
api=lambda method,path,body=None:m.request("http://127.0.0.1:18783",private["credentials"]["Owner"]["token"],method,path,body)
for path,h in frozen["hashes"].items():assert m.digest(path)==h,path
assert not (C/"execution-intent.json").exists(),"Inspect original outcome, do not repeat"
def answer(att,decision):
 aid=str(att["id"]);label="answer-"+aid
 receipt=api("GET","attention/"+aid);assert receipt["canRespond"]
 allowed={"participant-facts.txt","participant-approval.txt","participant-rejection.txt","participant-source-redirect.txt","participant-no-new-decisions.txt"}
 assert decision["reviewerKind"]=="coordinator-scripted-QA-participant"
 files=decision["selectedFiles"];assert files and all(x in allowed for x in files)
 if "participant-approval.txt" in files:
  assert len(decision["rubric"])==len(json.loads((C/"participant-rubric.json").read_text())["criteria"]) and all(x["satisfied"] for x in decision["rubric"])
  assert decision["proposalSources"],"Review exact canonical question or current artifacts, not a presumed Markdown path"
  for source in decision["proposalSources"]:
   if source["kind"]=="file":assert m.digest(source["path"])==source["sha256"],"Proposal changed since review"
   else:assert source["kind"]=="canonical-question" and source["attentionId"]==aid
 text="\n\n".join((C/x).read_text() for x in files)
 if "participant-rejection.txt" in files:
  text+="\nRecorded unresolved criteria:\n"+"\n".join(x["criterion"] for x in decision["rubric"] if not x["satisfied"])
 operation="goal-discovery-continuation-r237:"+label
 questions=receipt["attention"]["request"]["questions"];first=questions[0]["id"]
 answers={q["id"]:{"answers":[text if i==0 else "The operational answer under "+first+" applies to this question as well; read that full answer. No additional approval is implied."]} for i,q in enumerate(questions)}
 encoded={"type":"hollywoodQuestionAnswer","attentionId":aid,"answers":answers}
 assert len(json.dumps(encoded).encode())<=6000,"Answer encoder preflight: preserve pending question, no oversized POST"
 body={"operationId":operation,"scope":receipt["scope"],"response":{"answers":answers}}
 return m.submit(C,label,api,"POST","attention/"+aid+"/response",body,"attention/"+aid+"/commands/"+operation)
def retire(db,reason):
 snap=m.snapshot(db,arm,peer)
 try:
  for d in snap["deliveries"]:
   if d["state"] not in ["completed","failed","cancelled","unknown"]:
    m.submit(C,"retire-"+str(d["id"]),api,"POST","deliveries/"+str(d["id"])+"/cancel",{},"deliveries/"+str(d["id"]))
  for who in [arm,peer]:
   row=api("GET","placements/"+who["agent"])
   m.administrative_put(C,api,"placements/"+who["agent"],{"operationId":"goal-discovery-continuation-r237:retire:"+who["agent"],"hostId":who["host"],"revision":row["placement"]["revision"],"enabled":False})
 finally:
  units=[*arm["units"].values(),*peer["units"].values(),*arm["infrastructure"]]
  subprocess.run(["systemctl","stop",*units],check=True,capture_output=True)
  m.saved(C/"retirement.json",{"at":time.time(),"state":reason,"unitPids":{u:m.pid(u) for u in units},"preserveOriginalReceiptsHistoriesAndArtifacts":True})
env=dict(x.split("=",1) for x in json.loads(subprocess.check_output(["docker","inspect","--format","{{json .Config.Env}}","harness-postgres"],text=True)) if "=" in x)
dbc=json.loads(Path("/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json").read_text());role=dbc["user"]
dbc.update(user=env["POSTGRES_USER"],password=env["POSTGRES_PASSWORD"],application_name="goal-discovery-actual-native-r234")
with psycopg.connect(**dbc,row_factory=dict_row,autocommit=True) as db:
 db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
 histories=m.snapshot(db,arm,peer)["contexts"];assert len(histories)==6 and all(x["active_turn"] is None for x in histories)
 baseline={a["agent"]:m.h.usage(c,"three") for a,c in [(arm,cfg),(peer,pcfg)]}
 m.saved(C/"execution-intent.json",m.h.serialize({"at":time.time(),"freezeSha256":m.digest(C/"freeze.json"),"historiesBefore":histories,"baselineUsage":baseline,"operatorModelRequests":1,"operatorPeerRequests":0,"noOriginalTaskReplayed":True}))
 state="observation-window-ended";original=None;initial=None;started=time.time();answered=[];quiet=None;last=None;approval_at=None;first_impl=None
 try:
  subprocess.run(["systemctl","start",*arm["infrastructure"]],check=True,capture_output=True)
  for who in [arm,peer]:
   row=api("GET","placements/"+who["agent"]);assert row["state"]=="paused"
   m.administrative_put(C,api,"placements/"+who["agent"],{"operationId":"goal-discovery-continuation-r237:enable:"+who["agent"],"hostId":who["host"],"revision":row["placement"]["revision"],"enabled":True})
  subprocess.run(["systemctl","start",*arm["units"].values(),*peer["units"].values()],check=True,capture_output=True)
  until=time.time()+60
  while not (m.ready(cfg) and m.ready(pcfg)):
   if time.time()>until:raise RuntimeError("Persistent histories not ready; no original task submitted")
   time.sleep(.5)
  now=m.snapshot(db,arm,peer)["contexts"]
  assert {(str(x["agent"]),x["purpose"],x["native_thread"]) for x in now}=={(str(x["agent"]),x["purpose"],x["native_thread"]) for x in histories}
  started=time.time();op="goal-discovery-continuation-r237:original"
  initial=m.submit(C,"original",api,"POST","rooms/"+arm["room"]+"/messages",{"operationId":op,"kind":"request","audience":"room","recipientId":arm["agent"],"body":(C/"request.txt").read_text()},"commands/"+op)
  original=initial["deliveries"][0]["id"]
  m.saved(C/"request-public.json",{"at":started,"originalDelivery":original,"originalEvent":initial["event"]["id"],"deadline":started+p["budgets"]["seconds"]})
  while time.time()<started+p["budgets"]["seconds"]:
   now=time.time();snap=m.snapshot(db,arm,peer)
   row=next(x for x in snap["deliveries"] if str(x["id"])==original)
   impl=Path(arm["workspace"])/"weekly_report.py"
   if first_impl is None and impl.exists():
    first_impl={"observedAt":now,"mtime":impl.stat().st_mtime,"sha256":m.digest(impl),"approvalAt":approval_at};m.saved(C/"first-implementation-observed.json",first_impl)
   for att in [x for x in snap["attention"] if x["state"]=="pending" and str(x["id"]) not in answered]:
    aid=str(att["id"]);rd=C/"participant-reviews";rd.mkdir(mode=0o700,exist_ok=True)
    needed=rd/(aid+"-needed.json");decision=rd/(aid+"-decision.json")
    if not needed.exists():
     m.saved(needed,m.h.serialize({"at":now,"attention":att,"originalDelivery":row,"workspace":arm["workspace"],"rubric":json.loads((C/"participant-rubric.json").read_text()),"policy":"Record explicit review decision against exact available artifacts/question; no assumed proposal filename or automatic approval."}))
     print(json.dumps({"participantReviewNeeded":str(needed),"questionAgent":str(att["agent"])}),flush=True)
    if decision.exists():
     assert len(answered)<p["budgets"]["participantAnswers"],"QA participant answer budget exceeded; no coaching"
     d=json.loads(decision.read_text());answer(att,d);answered.append(aid)
     if "participant-approval.txt" in d["selectedFiles"]:approval_at=time.time()
   cu=m.h.usage(cfg,"three");pu=m.h.usage(pcfg,"three")
   delta=cu["total_tokens"]+pu["total_tokens"]-sum(x["total_tokens"] for x in baseline.values())
   summary={"at":now,"originalState":row["state"],"activeContexts":sum(x["active_turn"] is not None for x in snap["contexts"]),"participantAnswers":len(answered),"reviewed":approval_at is not None,"implementationObserved":first_impl is not None,"addedReportedNativeTokens":delta}
   marker=json.dumps({k:v for k,v in summary.items() if k!="at"},sort_keys=True)
   if marker!=last:
    m.saved(C/"latest.json",m.h.serialize({"summary":summary,"snapshot":snap}))
    print(json.dumps(summary),flush=True);last=marker
   if delta>p["budgets"]["addedReportedNativeTokens"]:state="native-reported-usage-budget-exceeded";break
   terminal=all(x["state"] in ["completed","cancelled","failed","unknown"] for x in snap["deliveries"])
   if terminal and not any(x["active_turn"] for x in snap["contexts"]):
    if quiet is None:quiet=now
    if now-quiet>=12:state="settled" if row["state"]=="completed" else "settled-with-incomplete-original";break
   else:quiet=None
   time.sleep(1)
  snap=m.snapshot(db,arm,peer)
  scorer=runpy.run_path(str(C/"outcome_scorer.py"))
  checks=scorer["evaluate"](arm["workspace"],peer["workspace"],arm["host"],arm["linuxUser"])
  m.saved(C/"result.json",m.h.serialize({"at":time.time(),"state":state,"seconds":time.time()-started,"originalDelivery":original,"originalEvent":initial["event"]["id"],"snapshot":snap,"functionalChecks":checks,"participantAnswers":answered,"approvalAt":approval_at,"firstImplementation":first_impl,"initialHistories":histories,"baselineUsage":baseline,"consumerUsage":m.h.usage(cfg,"three"),"peerUsage":m.h.usage(pcfg,"three"),"operatorArtifactRepairs":0,"operatorPeerRequests":0,"sourceAndConversationAuditPending":True}))
  print(json.dumps({"state":state,"functionalPassed":sum(x["passed"] for x in checks),"functionalTotal":len(checks),"seconds":time.time()-started}),flush=True)
 except BaseException as error:
  m.saved(C/"runner-failure.json",{"at":time.time(),"error":type(error).__name__,"detail":str(error)[:700],"action":"Retain accepted original receipts; no retry, artifact repair or invented success."});raise
 finally:retire(db,state)

