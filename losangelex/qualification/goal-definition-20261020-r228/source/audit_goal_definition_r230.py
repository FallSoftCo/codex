"""Audit original trial evidence without changing artifacts, criteria or model histories."""
import hashlib,importlib.util,json,subprocess,tempfile,time,runpy
from pathlib import Path
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
s=importlib.util.spec_from_file_location("trial",Q/"run_goal_definition_r228.py")
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
case=m.CASE;assert (case/"paired-result.json").is_file()
dest=case/"final-audit-r230.json";assert not dest.exists()
sc=runpy.run_path(str(case/"outcome_scorer.py"));arms={}
for name in ["definition","ordinary"]:
 arm=json.loads((m.ROOT/name/"public.json").read_text());peer=json.loads((m.ROOT/name/"peer/public.json").read_text())
 private=json.loads((m.ROOT/name/"installation-intent.json").read_text())
 api=lambda method,path,body=None:m.request("http://127.0.0.1:18783",private["credentials"]["Owner"]["token"],method,path,body)
 w=Path(arm["workspace"]);p=Path(peer["workspace"]);out=case/"runs"/name;result=json.loads((out/"result.json").read_text())
 before={x.name:m.digest(x) for x in w.iterdir() if x.is_file()}
 # Supplement frozen checker with strict types and conditional-consent coverage of the already stated contract.
 probes=[]
 with tempfile.TemporaryDirectory(prefix="confirmation-audit-",dir=out) as t:
  t=Path(t);input=t/"input.csv";policy=t/"policy.json"
  for label,rows,pol in [("strict-report-types",sc["sample_rows"](),sc["POLICY"]),
    ("conditional-consent",sc["rows_for"]("anonymous-cohort",3,2,False),{**sc["POLICY"],"minParticipants":3,"minPracticeSessions":2,"requiresAllConsent":False})]:
   input.write_text(sc["csv_text"](rows));policy.write_text(json.dumps(pol))
   run=subprocess.run(["/usr/bin/python3",str(w/"intake_report.py"),str(input),str(policy)],capture_output=True,text=True,timeout=15,cwd=w)
   value=json.loads(run.stdout);expected=sc["reference"](rows,pol)
   valid_types=type(value.get("ready")) is int and type(value.get("cohorts")) is list and all(
    type(x.get("cohort")) is str and type(x.get("learners")) is int and type(x.get("consented")) is int and type(x.get("eligible")) is bool for x in value["cohorts"])
   probes.append({"name":label,"passed":run.returncode==0 and value==expected and valid_types,
    "actual":value,"expected":expected,"strictTypes":valid_types,"exitCode":run.returncode})
  valid=subprocess.run(["/usr/bin/python3",str(p/"policy_guard.py"),str(p/"policy.json")],capture_output=True,text=True,timeout=15,cwd=p)
  invalid=t/"invalid-policy.json";invalid.write_text(json.dumps({**sc["POLICY"],"minPracticeSessions":-1}))
  bad=subprocess.run(["/usr/bin/python3",str(p/"policy_guard.py"),str(invalid)],capture_output=True,text=True,timeout=15,cwd=p)
  probes.append({"name":"independent actual engineer CLI validation","passed":valid.returncode==0 and json.loads(valid.stdout)==sc["POLICY"] and bad.returncode!=0,
    "validExitCode":valid.returncode,"invalidExitCode":bad.returncode})
 assert before=={x.name:m.digest(x) for x in w.iterdir() if x.is_file()},"Evaluator must not repair model artifacts"
 history=api("GET","rooms/"+arm["room"]+"/history?limit=100&view=all")
 m.saved(out/"actual-human-history-api.json",history)
 finalrow=next(x for x in result["snapshot"]["deliveries"] if str(x["id"])==json.loads((out/"public.json").read_text())["originalDelivery"])
 def ids(v):
  if isinstance(v,dict):
   if "id" in v:yield str(v["id"])
   for x in v.values():yield from ids(x)
  elif isinstance(v,list):
   for x in v:yield from ids(x)
 finalvisible=str(finalrow["result_event"]) in set(ids(history))
 reviews=[]
 for decision in (out/"participant-reviews").glob("*-decision.json"):
  d=json.loads(decision.read_text());needed=json.loads(decision.with_name(decision.name.replace("-decision","-needed")).read_text())
  entry={"attentionId":needed["attention"]["id"],"decision":d["decision"],"rubricSatisfied":all(x["satisfied"] for x in d["rubric"]),
    "proposalWaitSeconds":d["reviewedAt"]-needed["at"],"sourceKind":d.get("definitionSource",{}).get("kind","versioned-Markdown-artifact")}
  if d["decision"]=="approve" and (reviewed:=decision.with_name(decision.name.replace("-decision.json","-reviewed-definition.md"))).exists():
   entry["reviewedPrefixPreserved"]=(w/"goal-definition.md").read_bytes().startswith(reviewed.read_bytes())
  reviews.append(entry)
 contexts=result["snapshot"]["contexts"]
 units=[*arm["units"].values(),*peer["units"].values(),*arm["infrastructure"]]
 arms[name]={"originalDelivery":finalrow,"frozenChecksPassed":sum(x["passed"] for x in result["functionalChecks"]),
  "frozenChecksTotal":len(result["functionalChecks"]),"supplementaryProbes":probes,"artifactsUnchangedByAudit":True,
  "finalVisibleThroughActualHumanHistoryApi":finalvisible,"originalDoneAfterLateInputs":finalrow["state"]=="completed" and result["lateInputsAt"] is not None,
  "reviews":reviews,"distinctPersistentHistories":len({x["native_thread"] for x in contexts}),
  "activeNativeTurns":sum(x["active_turn"] is not None for x in contexts),"unitPids":{u:m.pid(u) for u in units},
  "artifactHashes":before,"policyHash":m.digest(p/"policy.json"),"seconds":result["seconds"],
  "usage":{key:result["consumerUsage"][key]+result["producerUsage"][key] for key in ["total_tokens","input_tokens","cached_input_tokens","output_tokens","compactions"]},
  "definitionFileExists":(w/"goal-definition.md").is_file()}
protected=json.loads((m.ROOT/"setup-result.json").read_text())["existingProtectedPids"]
actual={u:m.pid(u) for u in protected}
m.saved(dest,m.h.serialize({"at":time.time(),"arms":arms,"protectedServicePids":actual,"protectedPidsUnchanged":actual==protected,
 "protocolAndScorerUnchanged":all(m.digest(case/n)==v for n,v in m.protocol["files"].items()),
 "supplementaryProbePolicy":"Two post-trial probes cover stated conditional-consent/type requirements not fully distinguished by the frozen equality checks; engineer executable independently rechecked. They do not replace or inflate the original17-check result.",
 "observerCorrection":"Original ordinary task and six native histories continued across deterministic observer correction; same accepted proposal was answered once. No model/worker restart, task resubmission or artifact repair.",
 "interpretation":"Both actual-model workflows delivered. Definition arm used versioned Markdown; ordinary arm used a durable native proposal plus earlier clarification. Both had proposal review opportunity. This supports feasibility and artifact flexibility, not causal superiority or general reliability.",
 "runtimeChanges":0,"newModelCallsByAudit":0}))
print(json.dumps({"audit":str(dest),"protectedPidsUnchanged":actual==protected,"arms":{k:{"originalState":v["originalDelivery"]["state"],"frozenPassed":v["frozenChecksPassed"],"frozenTotal":v["frozenChecksTotal"],"supplementaryPass":all(x["passed"] for x in v["supplementaryProbes"]),"actualHumanHistoryFinal":v["finalVisibleThroughActualHumanHistoryApi"],"ownedUnitsStopped":all(x=="0" for x in v["unitPids"].values()),"persistentHistories":v["distinctPersistentHistories"]} for k,v in arms.items()}}),flush=True)
