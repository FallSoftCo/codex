"""Read-only independent audit of the settled, original r232 continuation."""
import hashlib,importlib.util,json,subprocess,time
from datetime import datetime
from pathlib import Path
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
sp=importlib.util.spec_from_file_location("trial",Q/"run_goal_definition_r228.py")
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
c=m.ROOT/"goal-definition-compaction-r232";dest=c/"independent-audit-r233.json"
assert not dest.exists()
r=json.loads((c/"result.json").read_text());p=json.loads((c/"protocol.json").read_text())
a=json.loads((m.ROOT/"definition/public.json").read_text());b=json.loads((m.ROOT/"definition/peer/public.json").read_text())
secret=json.loads((m.ROOT/"definition/installation-intent.json").read_text())
api=lambda path:m.request("http://127.0.0.1:18783",secret["credentials"]["Owner"]["token"],"GET",path)
w=Path(a["workspace"]);v=Path(b["workspace"])
before={str(d):m.digest(d) for base in [w,v] for d in base.iterdir() if d.is_file()}
prior={n:{"expected":h,"actual":m.digest((v if n=="policy.json" else w)/n)} for n,h in p["oldArtifactHashes"].items()}
expected={"ready":0,"cohorts":[{"cohort":n,"learners":nlearn,"consented":consent,"eligible":False} for n,nlearn,consent in [("north",10,10),("river",10,10),("studio",10,9),("tiny",9,9)]]}
run=subprocess.run(["/usr/bin/python3","-B",str(w/"intake_report.py"),str(w/"intake.csv"),str(v/"policy-v3.json")],capture_output=True,text=True,cwd=w,timeout=15)
report=json.loads(run.stdout);sample=json.loads((w/"sample-report-current.json").read_text());evidence=json.loads((w/"summary-evidence.json").read_text())
policy=json.loads((v/"policy-v3.json").read_text())
validation=subprocess.run(["/usr/bin/python3","-B",str(v/"policy_guard.py"),str(v/"policy-v3.json")],capture_output=True,text=True,cwd=v,timeout=15)
summary=(w/"report-summary.md").read_text();addendum=(w/"goal-definition-addendum.md").read_text()
late=r["lateInput"]["event"];late_at=datetime.fromisoformat(late["created_at"]).timestamp()
rs=next(x for x in r["readerCompactions"] if x["event"]=="item/started")
rc=next(x for x in r["readerCompactions"] if x["event"]=="item/completed" and x["item"]["id"]==rs["item"]["id"])
original=next(x for x in r["snapshot"]["deliveries"] if x["id"]==r["originalDelivery"])
events=[];pages=[];cursor=None
for i in range(12):
 path="rooms/"+a["room"]+"/history?limit=100&view=all"+("&after="+str(cursor) if cursor is not None else "")
 page=api(path);m.saved(c/("human-history-r233-page-"+str(i+1)+".json"),page);pages.append(page)
 # History rows may contain structured activity as well as messages.
 def walk(value):
  if isinstance(value,dict):
   if "id" in value:yield value
   for x in value.values():yield from walk(x)
  elif isinstance(value,list):
   for x in value:yield from walk(x)
 events.extend(walk(page));n=page.get("nextCursor")
 if n is None:break
 assert n!=cursor
 cursor=n
else:raise RuntimeError("History pagination bound exceeded; do not pretend missing final")
ids={str(x["id"]) for x in events};final=next((x for x in events if str(x["id"])==original["result_event"]),None)
cfg=json.loads(Path(a["config"]).read_text())
reader_rows=[json.loads(x) for x in (Path(cfg["state"])/"reader/events.jsonl").read_text().splitlines()]
accepted=[x for x in reader_rows if x.get("event")=="reader_input_accepted" and late["id"] in x.get("inputIds",[])]
completed_compactions={purpose:[x for x in r[purpose+"Compactions"] if x["event"]=="item/completed"] for purpose in ["reader","writer"]}
same={(x["agent"],x["purpose"],x["native_thread"]) for x in r["snapshot"]["contexts"]}=={(x["agent"],x["purpose"],x["native_thread"]) for x in r["initialHistories"]}
strict=type(report["ready"]) is int and all(type(x["eligible"]) is bool and type(x["learners"]) is int and type(x["consented"]) is int for x in report["cohorts"])
ret=json.loads((c/"retirement.json").read_text())
protected=json.loads((m.ROOT/"setup-result.json").read_text())["existingProtectedPids"]
actual={u:m.pid(u) for u in protected}
privacy_ids={row.split(",")[1] for row in (w/"intake.csv").read_text().splitlines()[1:] if "," in row}
# CSV parser below selects the actual learner_id column rather than relying on order.
import csv
privacy_ids={x["learner_id"] for x in csv.DictReader((w/"intake.csv").read_text().splitlines())}
new_text="\n".join((w/n).read_text() for n in ["report-summary.md","sample-report-current.json","summary-evidence.json","goal-definition-addendum.md"])
checks={
 "settled-original-completed":r["state"]=="settled" and original["state"]=="completed",
 "reader-and-writer-real-compaction-completed":all(completed_compactions.values()),
 "same-six-persistent-histories":same and len(r["snapshot"]["contexts"])==6,
 "late-canonical-input-inside-reader-compaction":rs["at"]<late_at<rc["at"],
 "late-input-mechanically-accepted-in-that-turn":any(x.get("duringNativeTurn")==rs["turnId"] for x in accepted),
 "actual-current-policy-cli":run.returncode==0 and not run.stderr and report==expected and strict,
 "sample-and-evidence-match-actual":sample==report and evidence["report"]==report,
 "actual-engineer-policy-cli":validation.returncode==0 and json.loads(validation.stdout)==policy,
 "verified-current-policy-provenance":evidence["policy"]=={"revision":3,"hostId":a["host"],"path":str(v/"policy-v3.json"),"sha256":m.digest(v/"policy-v3.json")},
 "late-input-and-original-retained-in-evidence":evidence.get("sourceRequestId")==r["originalEvent"] and evidence.get("clarificationId")==late["id"] and late["id"] in addendum,
 "prior-artifacts-unchanged":all(x["expected"]==x["actual"] for x in prior.values()),
 "no-raw-learner-identifiers":not any(x and x in new_text for x in privacy_ids),
 "final-visible-through-actual-paginated-human-api":final is not None,
 "no-active-turns":not any(x["active_turn"] for x in r["snapshot"]["contexts"]),
 "all-eight-own-units-stopped":all(m.pid(u)=="0" for u in ret["ownedUnitPids"]),
 "temporary-native-configs-restored":all(isinstance(x,str) and not Path(x).exists() for x in ret["nativeHomeConfigRestoration"]),
 "protected-services-unchanged":actual==protected,
 "protocol-inputs-unchanged":all(m.digest(c/n)==h for n,h in p["files"].items()),
}
assert before=={str(d):m.digest(d) for base in [w,v] for d in base.iterdir() if d.is_file()}
result={"at":time.time(),"checks":checks,"original":original,"lateInputTime":late_at,"readerCompactionInterval":[rs["at"],rc["at"]],"readerAcceptance":accepted,"realCompactionCounts":{k:len(x) for k,x in completed_compactions.items()},"currentReport":report,"policy":policy,"oldHashes":prior,"protectedPids":actual,"actualHumanHistoryPages":len(pages),"finalEvent":final,"artifactsRepaired":0,"newModelCalls":0,"runtimeChanges":0,"seconds":r["seconds"],"nativeTokenDelta":sum(r[k]["total_tokens"] for k in ["consumerUsage","producerUsage"])-sum(x["total_tokens"] for x in r["baselineUsage"].values()),"qualificationScope":"One controlled report-only continuation after deliberately lowered native compaction thresholds. Criteria frozen before execution; this executable independent audit authored after outputs. No claim of statistical superiority, discovery quality, production readiness or exactly-once external effects."}
m.saved(dest,result)
print(json.dumps({"audit":str(dest),"checksPassed":sum(checks.values()),"checksTotal":len(checks),"failed":[k for k,v in checks.items() if not v],"compactions":result["realCompactionCounts"]}),flush=True)

