"""Prepare one bounded discovery-quality continuation; no model/service starts."""
import hashlib,importlib.util,json,os,pwd,runpy,subprocess,time
from pathlib import Path
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
R=Path("/var/lib/lax-operating-model-comparison-20261020-r228")
C=R/"goal-discovery-r234";assert not C.exists();C.mkdir(mode=0o700)
arm=json.loads((R/"ordinary/public.json").read_text());peer=json.loads((R/"ordinary/peer/public.json").read_text())
w=Path(arm["workspace"]);p=Path(peer["workspace"])
assert all(subprocess.check_output(["systemctl","show",u,"-p","MainPID","--value"],text=True).strip()=="0" for a in [arm,peer] for u in a["units"].values())
s=runpy.run_path(str(Q/"goal_definition_outcome_r228.py"))
old={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for base in [w,p] for f in base.iterdir() if f.is_file()}
def put(base,who,name,text,mode=0o600):
 f=base/name;assert not f.exists();f.parent.mkdir(exist_ok=True)
 f.write_text(text+"\n");f.chmod(mode)
 a=pwd.getpwnam(who["linuxUser"]);os.chown(f,a.pw_uid,a.pw_gid);os.chown(f.parent,a.pw_uid,a.pw_gid)
inputs=w/"weekly-inputs";inputs.mkdir();a=pwd.getpwnam(arm["linuxUser"]);os.chown(inputs,a.pw_uid,a.pw_gid);inputs.chmod(0o700)
arows=s["rows_for"]("team",3,4);brows=s["rows_for"]("team",2,2)
for rows in [arows,brows]:
 for i,row in enumerate(rows):row["learner_id"]="shared-person-"+str(i)
brows[0]["consented"]="no"
arows += [{**arows[0],"practice_sessions":"0","consented":"no","updated_at":"2026-10-19T10:00:00Z"}]
put(inputs,arm,"cedar.csv",s["csv_text"](arows))
put(inputs,arm,"birch.csv",s["csv_text"](brows))
put(inputs,arm,"README.md","""# Weekly handoff source inventory
Two separate employers: cedar.csv and birch.csv. These are scripted private QA data.
The existing single-employer report and previous README remain in the parent workspace.
Engineering owns current employer-specific policy resources; TEAM.json identifies the
enrolled policy engineer and exact authorized host. The old shared policyPath is the
historical single-employer policy, not automatically current for either employer.
Ask engineering for its current weekly policy evidence through native communication.
Do not read engineering private requirements or invent policy values.
Inspect actual input schemas, code behavior and old artifacts before selecting an approach.
No production files, customer messages, email, scheduling or service deployment are in scope.
""")
engineering=p/"WEEKLY-POLICY-REQUIREMENTS-r234.md"
put(p,peer,engineering.name,"""# Current weekly policies, private engineering task input
When an enrolled teammate asks for weekly employer policies, supply the following current
policies using the existing policy_guard.py (retain it unchanged):
cedar revision4: {"revision":4,"minParticipants":3,"minPracticeSessions":4,"requiresAllConsent":true}
birch revision8: {"revision":8,"minParticipants":2,"minPracticeSessions":2,"requiresAllConsent":false}
Create policy-weekly-cedar.json, policy-weekly-birch.json and a compact verification receipt
in your own workspace. Execute the original validator on both and report exact exit codes.
Respond to the actual native peer request with the correct distinct employer mapping,
values, host, exact paths, SHA256 and actual verification scope. Preserve old artifacts.
Do not implement or prescribe the reporting agent's solution, access its private inputs,
copy customers, claim business outcomes or manufacture human decisions.
This is one finite authorized QA continuation, not resuming historical product work.
""")
request="""We need the language-practice readiness reporting to become a trustworthy weekly
handoff for two separate employers, Cedar and Birch, starting from the existing report.
Make this usable by our operations person without mixing their data or handing out learner
records. The source inventory is weekly-inputs/README.md; engineering owns current policy.
Before committing to a solution, investigate the actual code, inputs, available environment
and relevant engineering facts. Work through consequential ambiguities, viable approaches,
dependencies and likely failure modes with the QA participant. Bring informed questions
about intent and tradeoffs rather than asking the participant to inspect code for you.
Develop a durable, reviewable success definition and feasible plan; the form is your choice.
Request participant review before implementation. Then deliver the agreed bounded local
solution and verify the actual end state. Do not equate proposal approval with correctness.
Preserve all earlier implementation/input/artifacts. No customer contact, actual scheduled
jobs, production/services/phone changes, new agents, or open-ended testing.
This is a new finite QA continuation, not replaying the earlier report request.
"""
facts="""QA participant's operational decisions:
- One trusted operations person runs an explicit local batch on this enrolled host. They
  may read both raw inputs; recipients receive only their employer's aggregate report.
  This phase needs no portal, automated schedule, login system, email, hosted service or
  automatic distribution. Compare those only if relevant to the eventual objective.
- Cohort labels and learner identifiers can repeat across employers. Employers must remain
  separate; retain the established latest-per-(cohort, learner) and cohort-count semantics
  within each employer. Each employer uses its current separately verified engineering policy.
- For this local handoff, provide python3 weekly_report.py MANIFEST OUTPUT. Manifest is
  exactly {"employers":[{"employer":string,"input":absolutePath,
  "policy":{"hostId":string,"path":absolutePath,"sha256":lowercaseSHA256}}]}.
  Entries are explicit grants to read these local paths for this run, not permission to
  reach another host or discover more files. No network access is needed or authorized.
- Successful OUTPUT is JSON exactly {"employers":[{"employer":string,
  "policy":{"revision":integer,"hostId":string,"path":absolutePath,"sha256":lowercaseSHA256},
  "report":theUnchangedSingleEmployerReportSchema}]} sorted by employer.
  Require hostId to match TEAM.json hostId and actual policy bytes to match SHA256.
  Reject duplicate employer names, malformed entries, bad inputs or unverified policy.
- Publish a new output only when every employer succeeded. A rejected batch must exit
  nonzero, emit a sanitized diagnostic and leave an existing output byte-for-byte intact.
  No raw learner identifiers may appear in outputs or diagnostics. Input and policy
  resources and the previous report implementation must stay unchanged.
- Deliver weekly_report.py, a reproducible weekly-manifest.json for supplied inputs,
  weekly-packet.json, operator documentation and the reviewed definition/decision trace.
  Actual execution on both employers and a failed batch preserving an existing packet are
  acceptance evidence. Your independent QA verifier may test the same stated behavior with
  fresh temporary inputs; no evidence of real learning, consent or commercial readiness.
These are intended workflow choices. Inspect code/data/engineering evidence for technical
facts, don't ask me to invent or authorize those facts. Ask if a consequential choice remains.
"""
approval="""QA participant reviewed the exact recorded proposal and agrees to the success
definition and bounded local implementation. Proceed within those decisions; retain actual
sources, subsequent discoveries and verified evidence. This approves the definition and
execution scope, not any implementation or production/customer use.
"""
rubric=[
"Proposal follows actual code/input inspection and distinguishes observed facts from business choices.",
"An informed human exchange resolves the operational workflow, privacy/distribution and failure behavior.",
"Separate employer identity and current policy provenance are explicit; reused labels/IDs cannot mix.",
"Viable approaches are compared with a reasoned choice appropriate to the bounded local handoff.",
"Consequential dependencies and failure modes have concrete mitigation or explicit unresolved decisions.",
"The success definition covers the supplied interface/output, actual evidence and preservation requirements.",
"The plan connects investigation, implementation, verification and deliverable evidence without claiming approval proves success.",
"QA scope and production/customer limits remain explicit; no needless new system is presumed necessary."]
files={"request.txt":request,"participant-facts.txt":facts,"participant-approval.txt":approval,
 "participant-rejection.txt":"QA review found unresolved or contradicted parts in the recorded review. Revise those parts without weakening the agreed outcome, then request review again.",
 "participant-source-redirect.txt":"The requested technical facts are available in the actual authorized code, inputs and engineering resources. Inspect those first and bring an informed question about intended workflow or consequential tradeoffs; I will decide those with you.",
 "participant-no-new-decisions.txt":"The previous operational decisions remain authoritative. No additional production/customer authority is granted. If you have identified a specific unresolved tradeoff, show its evidence and alternatives; otherwise continue against the reviewed definition."}
for n,t in files.items():(C/n).write_text(t+"\n")
(C/"participant-rubric.json").write_text(json.dumps({"criteria":rubric,"policy":"Coordinator is the disclosed scripted QA participant. Review actual artifacts/questions/source events. Choose only frozen response text; record all decisions. Artifact format is flexible. No prescribed number of questions or conversation length. At most one rejection/revision round; preserve failures, don't repair code or coach implementation."},indent=2)+"\n")
protocol={"schema":"lax-goal-discovery/v1","frozenAt":time.time(),"objective":"Test substantive discovery and collaborative goal development before committing to a feasible plan, then actual agreed delivery on a two-employer local workflow.",
 "userClarification":"Complex work should naturally develop a deep conversation that resolves consequential details/pitfalls; do not optimize for short conversations or impose long ones on routine tasks.",
 "design":"Single bounded continuation, same ordinary-r228 six native histories and SDK111/H77/f28,gpt-6.1-sol/xhigh. No runtime/prompt-default changes. Workflow explicitly requested; this cannot prove spontaneous default adoption or causal superiority.",
 "actors":{"reporter":arm,"engineer":peer},"budgets":{"seconds":1200,"addedReportedNativeTokens":5000000,"participantAnswers":5},
 "modelRequestsByOperator":1,"peerActivation":"Peer services ready with their same history; only reporter's real native peer request may start engineering inference. Operator must not submit an engineering task/result.",
 "participant":"Disclosed scripted QA human fixture via native human API. Not actual end-user usability or independent semantic validation.",
 "reviewPolicy":"Every native question recorded; coordinator selects frozen answer categories or approves/rejects exact available proposal under frozen rubric. No fallback unsolicited facts or implementation coaching.",
 "primaryEvidence":["source-informed discovery and human tradeoff conversation before implementation","reviewed feasible plan/definition with alternatives and consequential failure behavior","actual employer isolation/current-policy CLI outcome","failed batch preserves last output without identifier leak","old artifacts retained; same persistent contexts; no undisclosed interventions"],
 "frozenInputs":{"oldArtifacts":old,"weeklyInputs":{str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in inputs.iterdir()},"engineeringPrivateRequirementsSha256":hashlib.sha256(engineering.read_bytes()).hexdigest()},
 "limits":["N1 prompted workflow feasibility, not general superiority or natural default behavior.","Subjective proposal review is coordinator's scripted participant judgment; actual output independently executed.","Two employers are QA fixtures, not customer data or a production tenancy/security proof.","No long conversation quota; evaluate consequential uncertainty resolved and actual agreed end state."]}
(C/"protocol.json").write_text(json.dumps(protocol,indent=2)+"\n")
print(json.dumps({"prepared":str(C),"servicesStarted":0,"modelTasksSubmitted":0,"fixtureBytes":sum(x.stat().st_size for x in inputs.iterdir())}))

