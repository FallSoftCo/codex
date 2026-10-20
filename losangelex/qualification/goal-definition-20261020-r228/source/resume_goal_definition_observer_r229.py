"""Resume deterministic observation of the original r228 ordinary trial; no task replays."""
import importlib.util,json,os,signal,subprocess,time,runpy
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
s=importlib.util.spec_from_file_location("original_trial",Q/"run_goal_definition_r228.py")
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
case=m.CASE;out=case/"runs/ordinary"
handoff=json.loads((case/"observer-correction-intent.json").read_text())
receipt=case/"observer-correction-handoff.json";assert not receipt.exists()
a=json.loads((m.ROOT/"ordinary/public.json").read_text());peer=json.loads((m.ROOT/"ordinary/peer/public.json").read_text())
private=json.loads((m.ROOT/"ordinary/installation-intent.json").read_text())
api=lambda method,path,body=None:m.request("http://127.0.0.1:18783",private["credentials"]["Owner"]["token"],method,path,body)
cfg=json.loads(Path(a["config"]).read_text());pcfg=json.loads(Path(peer["config"]).read_text())
public=json.loads((out/"public.json").read_text());original=public["originalDelivery"]
native=api("GET","deliveries/"+original)
native=native.get("delivery",native)
assert native["state"] in ["running","claimed","completed"]
assert all(int(m.pid(u))>1 for u in [*a["units"].values(),*peer["units"].values()])
old=handoff["originalObserverPid"]
assert next(l for l in Path("/proc",str(old),"status").read_text().splitlines() if l.startswith("State:")).split()[1]=="T"
m.saved(receipt,{"at":time.time(),"oldObserverPid":old,"newObserverPid":os.getpid(),"originalDelivery":original,
 "meaning":"Resume same accepted operations after correcting observer artifact assumption; original protocol, scorer, task bodies and native model output unchanged.",
 "modelActivations":0,"newTaskSubmissions":0,"newAnswersSubmittedByThisObserver":0,"originalNativeWorkerPids":{u:m.pid(u) for u in [*a["units"].values(),*peer["units"].values()]}})
os.kill(old,signal.SIGKILL)
env=dict(x.split("=",1) for x in json.loads(subprocess.check_output(["docker","inspect","--format","{{json .Config.Env}}","harness-postgres"],text=True)) if "=" in x)
dbconfig=json.loads(Path("/var/lib/harness-deployments/ozzz-native-20261019-r01/database.json").read_text());role=dbconfig["user"]
dbconfig.update(user=env["POSTGRES_USER"],password=env["POSTGRES_PASSWORD"],application_name="goal-definition-observer-resume-r229")
state="observation-window-ended";last=None;quiet=None
with psycopg.connect(**dbconfig,row_factory=dict_row,autocommit=True) as db:
 db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
 try:
  while time.time()<public["deadline"]:
   snap=m.snapshot(db,a,peer);cu=m.h.usage(cfg,"three");pu=m.h.usage(pcfg,"three")
   orig=next(x for x in snap["deliveries"] if str(x["id"])==original)
   summary={"at":time.time(),"originalDeliveryState":orig["state"],"activeContexts":sum(x["active_turn"] is not None for x in snap["contexts"]),
    "consumerTokens":cu["total_tokens"],"producerTokens":pu["total_tokens"],"observerVersion":"r229",
    "pendingQuestions":[str(x["id"]) for x in snap["attention"] if x["state"]=="pending"]}
   marker=json.dumps({k:v for k,v in summary.items() if k!="at"},sort_keys=True)
   if marker!=last:
    m.saved(out/"latest.json",m.h.serialize({"summary":summary,"snapshot":snap,"consumerUsage":cu,"producerUsage":pu}))
    with (out/"observations.jsonl").open("a") as f:f.write(json.dumps(m.h.serialize({"summary":summary,"snapshot":snap}))+"\n")
    print(json.dumps({"arm":"ordinary",**summary}),flush=True);last=marker
   if cu["total_tokens"]+pu["total_tokens"]>m.protocol["budgets"]["totalReportedNativeTokensPerArmCeiling"]:
    state="native-reported-usage-budget-exceeded";break
   terminal=all(x["state"] in ["completed","cancelled","failed","unknown"] for x in snap["deliveries"])
   if terminal and summary["activeContexts"]==0:
    if quiet is None:quiet=time.time()
    if time.time()-quiet>=12:state="settled" if orig["state"]=="completed" else "original-"+orig["state"];break
   else:quiet=None
   time.sleep(1)
  snap=m.snapshot(db,a,peer);w=Path(a["workspace"]);scores=runpy.run_path(str(case/"outcome_scorer.py"))["evaluate"](w)
  fixed=json.loads((case/"ordinary-fixed-inputs.json").read_text())
  reviews=[json.loads(p.read_text()) for p in (out/"participant-reviews").glob("*-decision.json")]
  facts=json.loads((out/"facts-exposure.json").read_text())
  late=json.loads((out/"clarification-receipt.json").read_text()) if (out/"clarification-receipt.json").exists() else None
  result={"at":time.time(),"arm":"ordinary","state":state,"seconds":time.time()-public["startedAt"],
   "functionalChecks":scores,"snapshot":snap,"consumerUsage":m.h.usage(cfg,"three"),"producerUsage":m.h.usage(pcfg,"three"),
   "factsAt":facts["at"],"lateInputsAt":late["at"] if late else None,"participantAnswerRounds":2,"proposalReviews":reviews,
   "sourceRetained":m.digest(w/"intake.csv")==fixed["intake.csv"],"explicitParticipantPolicy":True,"operatorImplementationRepairs":0,
   "observerCorrection":str(receipt),"scope":"Same original actual-model software workflow; observer corrected a file-only assumption. No models/tasks restarted or artifacts repaired."}
  m.saved(out/"result.json",m.h.serialize(result))
  print(json.dumps({"arm":"ordinary","state":state,"functionalChecksPassed":sum(x["passed"] for x in scores),"functionalChecksTotal":len(scores),"seconds":result["seconds"]}),flush=True)
 except BaseException as e:
  m.saved(out/"resumed-observer-failure.json",{"at":time.time(),"error":type(e).__name__,"detail":str(e)[:1000],"taskReplays":0})
  raise
 finally:m.retire(out,a,peer,api,db,state)
m.saved(case/"paired-result.json",{"at":time.time(),"outcomes":{name:json.loads((case/"runs"/name/"result.json").read_text()) for name in ["definition","ordinary"]},
 "claim":"Recorded pilot observations; both arms may use definition, observer corrected, no automatic superiority verdict."})
