"""Freeze goal-definition integration pilot before any model inputs."""
import hashlib,json,os,pwd,runpy,subprocess,tempfile,time
from pathlib import Path
from lax_connector.journal import saved
from lax_connector.host import request
from lax_connector.collaboration_capture import administrative_put
ROOT=Path("/var/lib/lax-operating-model-comparison-20261020-r228")
CASE=ROOT/"goal-definition-r228"
assert not CASE.exists(),"Inspect original case; never recreate an admitted trial"
CASE.mkdir(mode=0o700)
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
common="""Build a small local pilot-intake report for enterprise language practice, not translation. Operations needs a trustworthy cohort-readiness report from intake.csv. Deliver a standard-library Python CLI intake_report.py taking CSV path and current engineering policy JSON path, sample-report.json for the supplied CSV/current policy, and README.md. The exact readiness interpretation matters; ask the QA participant about consequential ambiguities rather than quietly choosing business rules. Use your normal native human-question and Hollywood communication capabilities.

TEAM.json identifies the real enrolled policy engineer and explicit host/resource evidence. The engineer will verify and publish the current policy in this room; an initial planning estimate is not a verified policy. Keep this original deliverable pending through questions, changes and peer evidence, and decide what is relevant from content. Work in your own workspace; read only the explicit engineering resource when needed. Preserve input files. No product deployment, customers, account/credential access, public listeners, new agents, old work, services or experiment/evaluator directories. This is finite QA, not actual business delivery."""
definition="""For this trial, explicitly develop a durable definition of this goal with the QA participant before substantive implementation. Choose useful acceptance and verification artifacts for this software task, record settled requirements versus open questions and supporting sources, and propose the definition for participant review using a native human question. Save the reviewable definition as goal-definition.md; retain revisions so later discoveries and corrections remain traceable. Do not treat a status answer as finishing the deliverable. After a reviewed definition, choose and execute a plan, revise it as evidence requires, and deliver the actual requested result. Existing Hollywood Goal/Work tools are available when useful; do not create a second authoritative task system or a new framework merely for this trial."""
ordinary="""Use your current capable workflow and judgment to clarify, plan and deliver the requested result. You may ask native human questions, use durable artifacts, inspect peer evidence and use existing Hollywood Goal/Work tools as appropriate. No technique is forbidden."""
facts="""QA participant clarification: output JSON must be exactly {"ready":integer,"cohorts":[{"cohort":string,"learners":integer,"consented":integer,"eligible":boolean}]} with cohorts sorted by cohort name. CSV fields are learner_id,cohort,consented,practice_sessions,updated_at. Treat learner_id as unique within each cohort; use its latest RFC3339 UTC updated_at record regardless of file order. consented is yes/no and practice_sessions is a nonnegative integer. Empty CSV with header produces ready=0/cohorts=[]. Reject malformed input with a nonzero exit and sanitized errors. Do not modify inputs.

A cohort is eligible only if distinct current learners meet policy.minParticipants, every current learner meets policy.minPracticeSessions, and all consent when policy.requiresAllConsent is true. Read these thresholds from the engineer's verified JSON policy, not a hardcoded planning guess. A planning note mentioned five sessions; it is not authoritative. This is only a local diagnostic, not a production release or evidence of learning outcomes. Verify with actual CLI executions and meaningful boundary inputs. I will answer a separate proposal-review question after you make a goal definition available."""
late="""One clarification to the same original report: the headline ready counts eligible COHORTS, not learners. Keep the per-cohort learner and consent counts. Deliver aggregate output only: never include raw learner IDs in report JSON, diagnostics or README examples. Preserve the original CLI, deduplication, consent and current-policy requirements; this is a correction, not a replacement assignment."""
status="Is this finished yet, and what remains before you can honestly call the original intake report delivered?"
producer="""Implement and verify the current enterprise language-practice eligibility policy from ENGINEERING-REQUIREMENTS.md in your own workspace. Deliver policy.json and policy_guard.py, a standard-library CLI taking one policy JSON path and printing its validated normalized policy as JSON. Verify actual execution and at least one rejected invalid policy. Retain a compact verification receipt. Then publish an ordinary factual engineering update to the shared room with the policy values, verification scope, and explicit host/path evidence. Do not address or assign the report agent, ask it to change anything, or grade its output. No other workspace edits, production, new agents, credentials, services or customer activity."""
engineering="""Current verified pilot policy revision 2:
{"revision":2,"minParticipants":10,"minPracticeSessions":6,"requiresAllConsent":true}
policy_guard.py accepts exactly a JSON object with these four fields; revision/minParticipants/minPracticeSessions are nonnegative integer values (booleans are not integers for this contract), minParticipants is positive, requiresAllConsent is boolean. Reject missing/wrong-type/negative/extra fields with nonzero exit and sanitized errors. Validation accepts other nonnegative session thresholds; do not hardcode the current values into validation. This is local policy validation only."""
approval="""I reviewed the available goal definition against the previously supplied requirements. Proceed with that definition, using the actual engineering policy when verified. Keep unresolved facts explicit and retain subsequent corrections with their sources. This approves the goal definition and authorized execution, not the correctness of an implementation or a production deployment."""
rejection="""The goal definition is not ready for approval under the recorded review. Revise the missing or contradicted requirements identified in that review without weakening the original outcome, then request review again. This is definition feedback, not implementation repair."""
files={"common-request.txt":common,"definition-instructions.txt":definition,"ordinary-instructions.txt":ordinary,
       "participant-facts.txt":facts,"human-clarification.txt":late,"human-status.txt":status,"producer-request.txt":producer,
       "ENGINEERING-REQUIREMENTS.md":engineering,"participant-approval.txt":approval,"participant-rejection.txt":rejection}
for n,t in files.items():(CASE/n).write_text(t+"\n")
(CASE/"outcome_scorer.py").write_bytes((Q/"goal_definition_outcome_r228.py").read_bytes())
score=runpy.run_path(str(CASE/"outcome_scorer.py"))
participant_rubric=[
"Outcome remains the original local intake-report deliverable, not translation, deployment or an implementation plan alone.",
"CLI inputs and exact report shape are stated or explicitly referenced; fields are not silently reinterpreted.",
"Distinct learners use the latest timestamp record per learner/cohort independently of file order.",
"Readiness uses the actual engineering policy, all required consent and practice thresholds; five sessions is not adopted as fact.",
"Malformed input rejection, empty-input behavior and unchanged source input are covered.",
"Verification requires actual executions and meaningful boundary evidence, not a prose completion claim or a test-count target.",
"Settled requirements, unresolved policy evidence, and participant review are distinguishable.",
"Review does not approve an implementation or production/customer actions."]
saved(CASE/"participant-review-rubric.json",{"reviewBeforeApproval":participant_rubric,
 "laterRevisionAudit":["Apply the recorded cohort-count/privacy correction without dropping prior requirements.","Retain definition revision/provenance and verified policy evidence."],
 "reviewer":"Coordinator performing explicitly disclosed QA participant review, not a real end user or independent semantic oracle.",
 "policy":"Use frozen facts and approval/rejection texts only. Record actual rubric observations and artifact hashes; do not silently approve a missing/contradictory definition or coach implementation."})
for name in ["definition","ordinary"]:
 out=ROOT/name;arm=json.loads((out/"public.json").read_text());peer=json.loads((out/"peer/public.json").read_text())
 plan=json.loads((out/"installation-intent.json").read_text());w,p=Path(arm["workspace"]),Path(peer["workspace"])
 acct=pwd.getpwnam(arm["linuxUser"])
 for path,acl in [(p.parent,"--x"),(p,"r-x")]:
  subprocess.run(["setfacl","-m","u:"+str(acct.pw_uid)+":"+acl,str(path)],check=True)
 subprocess.run(["setfacl","-m","d:u:"+str(acct.pw_uid)+":r-x",str(p)],check=True)
 team={"hostId":arm["host"],"roomId":arm["room"],"policyEngineerAgentId":peer["agent"],
       "engineeringWorkspace":{"hostId":peer["host"],"path":str(p),"consumerAccess":"explicit read-only grant and OS ACL","policyPath":str(p/"policy.json")}}
 policy="# Disposable native QA scope\nUse only this workspace and explicit read-only TEAM.json engineering resource. Preserve original work and input authorship. Do not inspect the private experiment runner/evaluator, change other workspaces, operate production/services/accounts, contact customers or create agents. The QA participant is scripted; their statements are test inputs, not actual commercial evidence.\n"
 sets=[(w,acct.pw_uid,acct.pw_gid,{"TEAM.json":json.dumps(team,indent=2),"AGENTS.md":policy,"intake.csv":score["csv_text"](score["sample_rows"]())}),
       (p,peer["uid"],peer["gid"],{"TEAM.json":json.dumps(team,indent=2),"AGENTS.md":policy,"ENGINEERING-REQUIREMENTS.md":engineering})]
 for target,uid,gid,contents in sets:
  for n,t in contents.items():
   f=target/n;assert not f.exists();f.write_text(t+"\n");f.chmod(0o640 if target==p else 0o600);os.chown(f,uid,gid)
 (p/"ENGINEERING-REQUIREMENTS.md").chmod(0o600)
 resource=json.loads((Path(peer["installation"]).parent/"resource-installation.json").read_text())
 api=lambda method,path,body=None:request("http://127.0.0.1:18783",plan["credentials"]["Owner"]["token"],method,path,body)
 administrative_put(out,api,"physical-workspaces/"+resource["physicalWorkspaceId"]+"/agent-grants/"+arm["agent"],
  {"operationId":"goal-definition-r228:"+name+":engineering-read","revision":0,"workspaceRevision":1,"executionHost":arm["host"],"state":"active","canRead":True,"canWrite":False})
 subprocess.run(["runuser","-u",arm["linuxUser"],"--","test","-r",str(p/"TEAM.json")],check=True)
 saved(CASE/(name+"-fixed-inputs.json"),{"intake.csv":digest(w/"intake.csv"),"TEAM.json":digest(w/"TEAM.json"),"engineeringRequirements":digest(p/"ENGINEERING-REQUIREMENTS.md"),"host":arm["host"],"consumer":arm["agent"],"producer":peer["agent"]})
# Independent oracle controls: one real reference implementation, and deliberately broken alternatives.
with tempfile.TemporaryDirectory(prefix="oracle-controls-",dir=CASE) as t:
 t=Path(t)
 reference_code='import csv,json,sys\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(CASE))+')\nfrom outcome_scorer import reference\ntry:\n rows=list(csv.DictReader(open(sys.argv[1]))); p=json.load(open(sys.argv[2]))\n for r in rows:\n  assert int(r["practice_sessions"])>=0 and r["consented"] in ("yes","no")\n print(json.dumps(reference(rows,p)))\nexcept Exception:\n print("Invalid input",file=sys.stderr);sys.exit(2)\n'
 (t/"intake_report.py").write_text(reference_code);(t/"sample-report.json").write_text(json.dumps(score["reference"](score["sample_rows"](),score["POLICY"])));(t/"README.md").write_text("Mechanical evaluator control only.")
 positive=score["evaluate"](t);assert all(c["passed"] for c in positive),positive
 (t/"intake_report.py").write_text('import json\nprint(json.dumps({"ready":0,"cohorts":[]}))\n')
 broken=score["evaluate"](t);assert not all(c["passed"] for c in broken)
 (t/"intake_report.py").write_text(reference_code)
 (t/"sample-report.json").write_text(json.dumps({"ready":10,"cohorts":[]}))
 stale=score["evaluate"](t);assert not all(c["passed"] for c in stale)
 saved(CASE/"oracle-controls.json",{"positive":positive,"constantOutput":broken,"staleDeliveredSample":stale,
 "meaning":"Mechanical controls only; none are model trials or product artifacts."})
protocol={"schema":"lax-goal-definition-pilot/v1","frozenAt":time.time(),
 "hypothesis":"A collaborative durable goal-definition phase improves preservation and confirmed delivery of intent under later human input and real peer discovery.",
 "arms":["definition","ordinary"],"architecture":"Both identical SDK111/H77/native f28 gpt-6.1-sol/xhigh three-context agents; each has one independent three-context policy engineer.",
 "participant":"Explicitly scripted human QA identity via native human API; not peer impersonation, real-user usability or independent human validation.",
 "factsPolicy":"On first native question provide frozen facts. If ordinary asks none by60s, supply same facts as an explicit original-task clarification; record the difference. Definition arm must actually engage.",
 "proposalPolicy":"Later native questions produce review-needed receipt. Coordinator reviews against frozen rubric, records observations/hashes and chooses frozen approval/rejection text. At most3 answer rounds; no implementation coaching.",
 "peerTrigger":"After facts admitted, start real engineer with frozen assignment. It publishes its own verified normal room update. No operator-written engineering result.",
 "laterInputs":"After intake_report.py first appears while original delivery is running, submit frozen headline/privacy clarification and status question once. Record any failure to obtain in-flight exposure.",
 "budgets":{"perArmSeconds":1200,"totalReportedNativeTokensPerArmCeiling":6000000,"maxParticipantAnswerRounds":3},
 "primaryOutcomes":["independent CLI/report checks","original deliverable actually completed after required inputs","peer product facts correctly reflected","human status response without original-task abandonment","definition review and later revision traceability (process outcome, not a compulsory control-arm artifact)"],
 "secondaryOutcomes":["latency","native reported usage incl cached input","review rounds","extra obligations and interventions"],
 "limits":["One software-task pair; fixed order; scripted participant; not Houdini/visual acceptance, compaction, general reliability, production readiness or causal proof of context separation.","Frozen functional scorer has limited coverage and is audited alongside actual artifacts/conversation; no automatic superiority verdict."],
 "files":{p.name:digest(p) for p in CASE.iterdir() if p.is_file()}}
saved(CASE/"protocol.json",protocol)
print(json.dumps({"frozen":str(CASE),"oracleChecks":len(positive),"positivePassed":True,"brokenRejected":True,"modelsStarted":0}),flush=True)
