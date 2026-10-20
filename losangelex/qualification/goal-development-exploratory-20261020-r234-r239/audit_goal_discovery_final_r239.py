"""Final independent audit, including a fresh valid input and verifier blind-spot control."""
import csv,hashlib,importlib.util,io,json,os,pwd,subprocess,tempfile,time,runpy
from pathlib import Path
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
sp=importlib.util.spec_from_file_location("m",Q/"run_goal_definition_r228.py");m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
C=m.ROOT/"goal-discovery-continuation-r237";p=json.loads((C/"protocol.json").read_text());r=json.loads((C/"result-r238.json").read_text());a=p["actors"]["reporter"];b=p["actors"]["engineer"];w=Path(a["workspace"]);peer=Path(b["workspace"]);acct=pwd.getpwnam(a["linuxUser"])
assert not(C/"final-audit-r239.json").exists()
before={str(x):m.digest(x) for base in [w,peer] for x in base.iterdir() if x.is_file()}
# This supplementary input was selected after the main run. Do not count it as part of the frozen11.
supp={"at":time.time(),"timing":"Post-trial supplementary coverage; frozen11 unchanged, no model repair or rerun.","criterion":"Same stated generic manifest/CSV contract, new valid data under same actual verified engineering policies; ready must change with input. No new employer or business requirement.","cedarExpected":{"ready":0,"cohorts":[{"cohort":"east","learners":2,"consented":2,"eligible":False},{"cohort":"west","learners":4,"consented":3,"eligible":False}]},"birchExpected":{"ready":1,"cohorts":[{"cohort":"east","learners":1,"consented":0,"eligible":False},{"cohort":"west","learners":3,"consented":1,"eligible":True}]}}
m.saved(C/"supplementary-valid-data-protocol-r239.json",supp)
def csvtext(rows):
 s=io.StringIO();q=csv.DictWriter(s,fieldnames=["learner_id","cohort","consented","practice_sessions","updated_at"]);q.writeheader();q.writerows(rows);return s.getvalue()
def rows(cohort,n,sessions,consented):
 return [{"learner_id":"fresh-private-"+str(i),"cohort":cohort,"consented":"yes" if i<consented else "no","practice_sessions":str(sessions),"updated_at":"2026-10-20T10:00:00Z"} for i in range(n)]
def own(f):
 os.chown(f,acct.pw_uid,acct.pw_gid);f.chmod(0o700 if f.is_dir() else 0o600)
def fresh(script,t):
 cedar=rows("west",4,4,4)+rows("east",2,4,2)
 cedar.insert(0,{**cedar[0],"consented":"no","updated_at":"2026-10-21T10:00:00Z"})
 birch=rows("west",3,2,1)+rows("east",1,2,0)
 entries=[]
 for name,rs in [("cedar",cedar),("birch",birch)]:
  f=t/(name+".csv");f.write_text(csvtext(rs));own(f);policy=peer/("policy-weekly-"+name+".json")
  entries.append({"employer":name,"input":str(f),"policy":{"hostId":a["host"],"path":str(policy),"sha256":m.digest(policy)}})
 manifest=t/"manifest.json";manifest.write_text(json.dumps({"employers":entries}));own(manifest);out=t/"packet.json"
 result=subprocess.run(["/usr/bin/python3","-B",str(script),str(manifest),str(out)],cwd=w,capture_output=True,text=True,timeout=20,user=acct.pw_uid,group=acct.pw_gid)
 try:value=json.loads(out.read_text())
 except (OSError,json.JSONDecodeError):value=None
 expected={"employers":[{"employer":entry["employer"],"policy":{"revision":8 if entry["employer"]=="birch" else 4,**entry["policy"]},"report":supp[entry["employer"]+"Expected"]} for entry in sorted(entries,key=lambda e:e["employer"])]}
 return {"passed":result.returncode==0 and value==expected,"exitCode":result.returncode,"actual":value,"expected":expected,"noPrivateIds":not any("fresh-private-"+str(i) in result.stdout+result.stderr+(out.read_text() if out.exists() else "") for i in range(4))}
control_code='''import csv,hashlib,json,sys
from pathlib import Path
try:
 manifest=json.loads(Path(sys.argv[1]).read_text());host=json.loads(Path("TEAM.json").read_text())["hostId"];seen=set();out=[]
 for e in manifest["employers"]:
  assert e["employer"] not in seen;seen.add(e["employer"])
  p=e["policy"];assert p["hostId"]==host and hashlib.sha256(Path(p["path"]).read_bytes()).hexdigest()==p["sha256"]
  for row in csv.DictReader(Path(e["input"]).read_text().splitlines()):assert int(row["practice_sessions"])>=0
  n=3 if e["employer"]=="cedar" else 2;c=3 if e["employer"]=="cedar" else 1
  out.append({"employer":e["employer"],"policy":{"revision":json.loads(Path(p["path"]).read_text())["revision"],**p},"report":{"ready":1,"cohorts":[{"cohort":"team","learners":n,"consented":c,"eligible":True}]}})
 Path(sys.argv[2]).write_text(json.dumps({"employers":sorted(out,key=lambda e:e["employer"])}))
except Exception:
 print("Invalid packet",file=sys.stderr);sys.exit(2)
'''
with tempfile.TemporaryDirectory(prefix="final-outcome-audit-",dir=w) as td:
 t=Path(td);own(t);actual=fresh(w/"weekly_report.py",t)
 control=t/"deliberately-hardcoded-control.py";control.write_text(control_code);own(control)
 frozen_controls=runpy.run_path(str(C/"outcome_scorer.py"))["evaluate"](w,peer,a["host"],a["linuxUser"],control)
 # Remove the first supplementary output, so a control cannot pass by leaving the real output untouched.
 (t/"packet.json").unlink()
 hardcoded=fresh(control,t)
assert before=={str(x):m.digest(x) for base in [w,peer] for x in base.iterdir() if x.is_file()}
secret=json.loads((m.ROOT/"ordinary/installation-intent.json").read_text());api=lambda path:m.request("http://127.0.0.1:18783",secret["credentials"]["Owner"]["token"],"GET",path)
finalrow=next(x for x in r["snapshot"]["deliveries"] if x["id"]==r["originalDelivery"]);all_events=[];cursor=0;pages=0
for i in range(12):
 page=api("rooms/"+a["room"]+"/history?limit=100&view=all&after="+str(cursor));m.saved(C/("actual-human-history-r239-page-"+str(i+1)+".json"),page);pages+=1;all_events+=page["events"];n=page.get("nextCursor")
 if n is None or (n==cursor and not page["events"]):break
 assert n!=cursor;cursor=n
else:raise RuntimeError("Incomplete history audit")
def walk(x):
 if isinstance(x,dict):
  if "id" in x:yield x
  for v in x.values():yield from walk(v)
 elif isinstance(x,list):
  for v in x:yield from walk(v)
visible={str(e["id"]):e for e in walk(all_events)}
review=json.loads((w/"weekly-review.json").read_text())
attention=api("attention/0dc043b0-f700-51db-abff-851a886f7d4a")
approved_file=C/"participant-reviews/0dc043b0-f700-51db-abff-851a886f7d4a-reviewed-definition.json"
approved=json.loads(approved_file.read_text());definition=json.loads((w/"weekly-definition.json").read_text())
old={path:{"expected":h,"actual":m.digest(path)} for path,h in p["frozenInputs"]["oldArtifacts"].items()}
inputs={path:{"expected":h,"actual":m.digest(path)} for path,h in p["frozenInputs"]["weeklyInputs"].items()}
original_before=json.loads((C/"execution-intent.json").read_text())["historiesBefore"]
same={(x["agent"],x["purpose"],x["native_thread"]) for x in original_before}=={(x["agent"],x["purpose"],x["native_thread"]) for x in r["snapshot"]["contexts"]}
protected=json.loads((m.ROOT/"setup-result.json").read_text())["existingProtectedPids"];current={u:m.pid(u) for u in protected}
ret=json.loads((C/"retirement-r238.json").read_text());packet=json.loads((w/"weekly-packet.json").read_text())
types=all(type(e["policy"]["revision"]) is int and type(e["report"]["ready"]) is int and all(type(x["learners"]) is int and type(x["consented"]) is int and type(x["eligible"]) is bool for x in e["report"]["cohorts"]) for e in packet["employers"])
answer=attention["attention"]["response_event"];answer_event=visible.get(answer)
approved_time=None
if answer_event:
 from datetime import datetime
 approved_time=datetime.fromisoformat(answer_event["created_at"]).timestamp()
checks={"continued-original-completed":r["state"]=="settled" and finalrow["state"]=="completed","frozen11-outcomes":all(x["passed"] for x in r["functionalChecks"]),"fresh-valid-input-outcome":actual["passed"],"fresh-input-privacy":actual["noPrivateIds"],"strict-report-primitive-types":types,"review-bound-to-exact-question-and-source":attention["attention"]["state"]=="closed" and m.digest(approved_file)=="5c008799a593f1dbf8ae84da54312528854131806df027a02aed8375dec484bb","approval-before-implementation":approved_time is not None and approved_time<(w/"weekly_report.py").stat().st_mtime,"accepted-contract-preserved":definition["contract_from_new_request"]==approved["contract_from_new_request"],"original-files-retained":all(v["expected"]==v["actual"] for v in old.values()),"source-inventory-retained":all(v["expected"]==v["actual"] for v in inputs.values()),"same-six-histories":same and len(original_before)==6,"no-active-native-turns":not any(x["active_turn"] for x in r["snapshot"]["contexts"]),"all-eight-own-units-stopped":all(m.pid(u)=="0" for u in ret["unitPids"]),"protected-services-unchanged":current==protected,"human-final-visible":finalrow["result_event"] in visible,"failed-predecessor-stays-cancelled":api("deliveries/c86c02df-e05d-4325-8c86-befc3aed2d21")["delivery"]["state"]=="cancelled"}
audit={"at":time.time(),"checks":checks,"frozenFunctionalPassed":sum(x["passed"] for x in r["functionalChecks"]),"frozenFunctionalTotal":len(r["functionalChecks"]),"supplementaryFreshOutcome":actual,"verifierBlindSpot":{"hardcodedBaselineControlPassesOriginal11":all(x["passed"] for x in frozen_controls),"originalControlChecks":frozen_controls,"freshInputRejectsHardcodedControl":not hardcoded["passed"],"interpretation":"Original normal-path evaluator used supplied input only; even an input-insensitive baseline report plus error rejection could pass11. Retain this coverage gap. Fresh valid-input supplementary probe distinguishes it, and actual model artifact passes. No claim all checks were preregistered or exhaustive."},"originalFinal":finalrow,"finalEvent":visible.get(finalrow["result_event"]),"proposalReview":review,"humanHistoryPages":pages,"approvedAt":approved_time,"implementationMtime":(w/"weekly_report.py").stat().st_mtime,"oldHashes":old,"inputHashes":inputs,"protectedPids":current,"artifactHashes":before,"operatorArtifactRepairs":0,"newModelCalls":0,"interpretation":"Exploratory workflow feasibility: actual source-informed conversation, exact proposal review, same-task execution and independently checked delivery. Failed cancelled predecessor, answer-encoder correction, explicit new authorization and observer budget extension retained. Not causal superiority, natural-default adoption, independent-human usability, general reliability or production promotion."}
m.saved(C/"final-audit-r239.json",audit)
print(json.dumps({"audit":str(C/"final-audit-r239.json"),"checksPassed":sum(checks.values()),"checksTotal":len(checks),"failed":[k for k,v in checks.items() if not v],"freshActualPass":actual["passed"],"hardcodedPassesOriginal":audit["verifierBlindSpot"]["hardcodedBaselineControlPassesOriginal11"],"freshRejectsHardcoded":not hardcoded["passed"]}),flush=True)

