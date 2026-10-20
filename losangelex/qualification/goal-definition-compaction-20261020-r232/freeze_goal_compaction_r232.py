"""Freeze bounded continuation with real native compaction and pending human input."""
import json,hashlib,time,os,pwd,subprocess
from pathlib import Path
from lax_connector.journal import saved
ROOT=Path("/var/lib/lax-operating-model-comparison-20261020-r228")
CASE=ROOT/"goal-definition-compaction-r232"
assert not CASE.exists(),"Inspect original case; do not recreate"
CASE.mkdir(mode=0o700);(CASE/"administration").mkdir(mode=0o700)
a=json.loads((ROOT/"definition/public.json").read_text());peer=json.loads((ROOT/"definition/peer/public.json").read_text())
cfg=json.loads(Path(a["config"]).read_text());pcfg=json.loads(Path(peer["config"]).read_text())
units=[*a["units"].values(),*peer["units"].values(),*a["infrastructure"]]
pid=lambda u:subprocess.check_output(["systemctl","show",u,"-p","MainPID","--value"],text=True).strip()
assert all(pid(u)=="0" for u in units)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
files=["intake.csv","intake_report.py","sample-report.json","README.md","goal-definition.md"]
w=Path(a["workspace"]);p=Path(peer["workspace"])
prior={n:sha(w/n) for n in files}
prior["policy.json"]=sha(p/"policy.json")
histories={who["agent"]:{purpose:json.loads((Path(conf["state"])/purpose/"context.json").read_text())["nativeThread"] for purpose in conf["homes"]} for who,conf in [(a,cfg),(peer,pcfg)]}
settings=[]
acct=pwd.getpwnam(a["linuxUser"])
for purpose,threshold in [("reader",30000),("writer",50000)]:
 target=Path(cfg["homes"][purpose])/"config.toml"
 assert not target.exists(),"Do not overwrite native home configuration"
 body="model_auto_compact_token_limit = "+str(threshold)+"\n"
 settings.append({"path":str(target),"purpose":purpose,"threshold":threshold,"wasAbsent":True,"sha256":hashlib.sha256(body.encode()).hexdigest(),"body":body,"uid":acct.pw_uid,"gid":acct.pw_gid})
request="""Continue the existing local language-practice reporting work under its reviewed definition, including the clarified per-cohort latest-record semantics and aggregate-only privacy requirements. This is a new bounded report-only follow-up, not a replay of the completed delivery.

An enrolled engineer will verify a new policy revision in the same explicitly authorized read-only engineering workspace. Preserve the old policy.json, intake.csv, intake_report.py, sample-report.json and README.md. Reuse the existing CLI; do not rewrite the implementation. Wait for and inspect the new actual policy evidence before declaring this follow-up delivered.

Deliver report-summary.md, sample-report-current.json (actual existing CLI output with the new policy), summary-evidence.json with report:<the actual report JSON> and policy:{revision,hostId,path,sha256}, and a short goal-definition-addendum.md linking this follow-up to the previously reviewed goal-definition.md and later human/engineering sources. The summary must communicate the actual current cohort readiness for Operations without learner identifiers. Record actual execution evidence and unchanged old-input/artifact hashes. Do not substitute a plan or status answer for these outputs. The explicit report-only extension is authorized; no additional proposal approval is needed unless a consequential unresolved business choice appears.

TEAM.json identifies the enrolled engineer and explicit host/resource. The old policyPath is historical revision2; the new publication will name its own artifact. Use Hollywood communication and distinguish verified policy from planning. No old work, product deployment, customer/account activity, other services or agents, private experiment files, dependency builds or writes outside your own workspace."""
late="""Clarification to the same pending report-summary follow-up ({originalEvent}): the summary must explicitly identify the VERIFIED policy revision and include its exact host, path and SHA256 provenance, alongside ready COHORT count and per-cohort aggregate counts. Preserve the original report-only deliverables, per-cohort latest-record, privacy and unchanged old-artifact requirements. Do not use remembered revision2/six-session values as current evidence or silently invent new policy values. This clarifies the original follow-up; it is not a replacement assignment."""
engineer="""Execute a new bounded policy-only follow-up in your own workspace. Read ENGINEERING-REQUIREMENTS-r232.md, preserve every original revision2 artifact and input, and create policy-v3.json with the new exact policy. Reuse the existing policy_guard.py to validate the file in a real subprocess, retain policy-v3-verification.json with commands/results and hashes, and publish one ordinary factual engineering update to the shared room containing current values, verification scope, explicit host/path and SHA256. Do not address/assign the report agent or grade its output. No code/framework rewrite, unrelated test expansion, other workspace edits, services, credentials, customers or new agents."""
engineering='Current policy revision3 is {"revision":3,"minParticipants":10,"minPracticeSessions":7,"requiresAllConsent":true}. Use a new policy-v3.json; preserve old policy.json and existing validator. Verify actual CLI execution. This is local policy validation only, not learner or production evidence.\n'
answer="""The explicit report-only extension and its same-task clarification authorize these outputs under the previously reviewed semantics. Preserve the old artifacts, use actual verified revision3 policy evidence, and provide provenance and aggregate results in the requested files. Do not treat this answer as proof the implementation/output is correct or as permission for unrelated activity."""
for n,body in [("request.txt",request),("late-clarification.txt",late),("engineer-request.txt",engineer),("ENGINEERING-REQUIREMENTS-r232.md",engineering),("participant-answer.txt",answer)]:(CASE/n).write_text(body+"\n")
f=p/"ENGINEERING-REQUIREMENTS-r232.md";assert not f.exists();f.write_text(engineering);f.chmod(0o600);os.chown(f,peer["uid"],peer["gid"])
saved(CASE/"native-config-intent.json",{"at":time.time(),"settings":settings,"meaning":"Only our completed QA reporter homes. Genuine native auto-compaction thresholds; model/effort/permissions unchanged. Restore by deleting only these unchanged owned files after test."})
for item in settings:
 target=Path(item["path"]);target.write_text(item["body"]);target.chmod(0o600);os.chown(target,item["uid"],item["gid"])
q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
protocol={"schema":"lax-goal-definition-compaction/v1","frozenAt":time.time(),"authority":a["authority"],"agents":[a["agent"],peer["agent"]],
 "historiesBefore":histories,"oldArtifactHashes":prior,"oldDefinitionMayNotBeRewritten":True,"model":"gpt-6.1-sol","effort":"xhigh","runtime":"SDK111/H77/native f28",
 "primaryInputTiming":"Submit original follow-up. On actual reader contextCompaction item/started, before completed, submit frozen human clarification once and the actual peer's frozen policy task once. No synthetic compaction notifications or model-written engineering update.",
 "budgets":{"seconds":900,"addedReportedNativeTokens":4000000,"compactionStartSeconds":180,"participantAnswers":1},
 "criteria":["actual reader and writer compaction completed in the same existing native histories","late human clarification accepted during actual reader compaction and later interpreted","original responsibility completed after late input and actual verified peer policy","new actual CLI output matches current policy3/minSessions7, giving ready0 without learner IDs","summary and evidence preserve original agreed semantics and exact policy provenance","old implementation, inputs, sample, README, goal definition and policy2 unchanged","same six persistent histories, no user-stopped owner resumed, no external effects replayed"],
 "limits":"One explicit report-only continuation, automatic compaction threshold deliberately lowered in disposable reporter homes. No general reliability/production/multihost/visual-workflow claim.",
 "files":{p.name:sha(p) for p in CASE.iterdir() if p.is_file() and p.name!="native-config-intent.json"}}
saved(CASE/"protocol.json",protocol)
print(json.dumps({"frozen":str(CASE),"sameHistories":histories,"thresholds":{x["purpose"]:x["threshold"] for x in settings},"modelsStarted":0}))
