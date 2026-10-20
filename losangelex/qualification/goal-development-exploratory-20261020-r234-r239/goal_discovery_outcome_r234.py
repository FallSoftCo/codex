"""Independent end-state integration checks for the frozen weekly-packet contract."""
import hashlib,json,os,pwd,shutil,subprocess,tempfile
from pathlib import Path
POLICIES={"cedar":{"revision":4,"minParticipants":3,"minPracticeSessions":4,"requiresAllConsent":True},"birch":{"revision":8,"minParticipants":2,"minPracticeSessions":2,"requiresAllConsent":False}}
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def evaluate(workspace,peer,host,linux_user,artifact=None):
 w=Path(workspace);p=Path(peer);script=Path(artifact) if artifact else w/"weekly_report.py"
 result=[];acct=pwd.getpwnam(linux_user)
 def check(n,ok,detail=None):result.append({"name":n,"passed":bool(ok),"detail":detail})
 check("agreed CLI delivered",script.is_file())
 if not script.is_file():return result
 with tempfile.TemporaryDirectory(prefix="weekly-outcome-",dir=w) as td:
  t=Path(td);t.chmod(0o700);os.chown(t,acct.pw_uid,acct.pw_gid)
  source={name:w/"weekly-inputs"/(name+".csv") for name in POLICIES}
  policy={name:p/("policy-weekly-"+name+".json") for name in POLICIES}
  missing=[str(x) for x in [*source.values(),*policy.values()] if not x.is_file()]
  check("actual engineering policy resources exist",not missing,missing)
  if missing:return result
  for name in POLICIES:check(name+" actual current engineering policy",json.loads(policy[name].read_text())==POLICIES[name])
  def manifest(overrides=None):
   return {"employers":[{"employer":n,"input":str((overrides or {}).get(n,source[n])),
    "policy":{"hostId":host,"path":str(policy[n]),"sha256":digest(policy[n])}} for n in ["cedar","birch"]]}
  out=t/"packet.json";inp=t/"manifest.json"
  def execute(value):
   inp.write_text(json.dumps(value));os.chown(inp,acct.pw_uid,acct.pw_gid);inp.chmod(0o600)
   return subprocess.run(["/usr/bin/python3","-B",str(script),str(inp),str(out)],cwd=w,text=True,capture_output=True,timeout=20,user=acct.pw_uid,group=acct.pw_gid)
  before={str(f):digest(f) for f in [*source.values(),*policy.values(),w/"intake_report.py"]}
  expected={"employers":[{"employer":n,"policy":{"revision":POLICIES[n]["revision"],"hostId":host,"path":str(policy[n]),"sha256":digest(policy[n])},
   "report":{"ready":1,"cohorts":[{"cohort":"team","learners":3 if n=="cedar" else 2,"consented":3 if n=="cedar" else 1,"eligible":True}]}} for n in ["birch","cedar"]]}
  normal=execute(manifest())
  try:actual=json.loads(out.read_text())
  except (OSError,json.JSONDecodeError):actual=None
  check("two-employer actual output/isolation/current provenance",normal.returncode==0 and actual==expected,{"exitCode":normal.returncode,"actual":actual,"expected":expected})
  private=["shared-person-"+str(i) for i in range(3)]
  check("successful packet and process diagnostics aggregate only",not any(x in normal.stdout+normal.stderr+(out.read_text() if out.exists() else "") for x in private))
  # A previous accepted packet must survive each rejected batch. This marker is QA evidence, never a repair of model artifacts.
  marker=b'{"previousAcceptedPacket":"must-remain-byte-identical"}\n'
  bad=t/"private-invalid.csv";bad.write_text("learner_id,cohort,consented,practice_sessions,updated_at\nprivate-rejected-learner,team,yes,broken,2026-10-20T10:00:00Z\n")
  os.chown(bad,acct.pw_uid,acct.pw_gid);bad.chmod(0o600)
  wronghash=manifest();wronghash["employers"][1]["policy"]["sha256"]="0"*64
  wronghost=manifest();wronghost["employers"][1]["policy"]["hostId"]="ffffffff-ffff-4fff-8fff-ffffffffffff"
  duplicate=manifest();duplicate["employers"][1]["employer"]="cedar"
  for label,value in [("malformed second employer",manifest({"birch":bad})),("unverified policy hash",wronghash),("other-host local-path refusal",wronghost),("duplicate employer",duplicate)]:
   out.write_bytes(marker);os.chown(out,acct.pw_uid,acct.pw_gid);out.chmod(0o600)
   r=execute(value)
   check(label+" rejects and preserves last packet",r.returncode!=0 and out.read_bytes()==marker and not any(x in r.stdout+r.stderr for x in private+["private-rejected-learner"]),{"exitCode":r.returncode,"outputPreserved":out.read_bytes()==marker,"diagnosticSanitized":not any(x in r.stdout+r.stderr for x in private+["private-rejected-learner"])})
  check("source inputs/policies/old implementation unchanged",before=={str(f):digest(f) for f in [*source.values(),*policy.values(),w/"intake_report.py"]})
 return result

