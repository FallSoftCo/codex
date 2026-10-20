"""Freeze evidence before any r234 model request; exercise verifier controls."""
import hashlib,json,os,pwd,runpy,shutil,tempfile,time
from pathlib import Path
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
C=Path("/var/lib/lax-operating-model-comparison-20261020-r228/goal-discovery-r234")
assert not (C/"freeze.json").exists()
p=json.loads((C/"protocol.json").read_text());a=p["actors"]["reporter"];acct=pwd.getpwnam(a["linuxUser"])
shutil.copy2(Q/"goal_discovery_outcome_r234.py",C/"outcome_scorer.py")
sc=runpy.run_path(str(C/"outcome_scorer.py"))
control_code='''import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
try:
 m=json.loads(Path(sys.argv[1]).read_text());dest=Path(sys.argv[2]);host=json.loads(Path("TEAM.json").read_text())["hostId"]
 entries=[];seen=set()
 for e in m["employers"]:
  assert e["employer"] not in seen;seen.add(e["employer"])
  pol=e["policy"];path=Path(pol["path"])
  assert pol["hostId"]==host and hashlib.sha256(path.read_bytes()).hexdigest()==pol["sha256"]
  value=json.loads(path.read_text())
  r=subprocess.run([sys.executable,"-B","intake_report.py",e["input"],str(path)],text=True,capture_output=True)
  assert r.returncode==0
  entries.append({"employer":e["employer"],"policy":{"revision":value["revision"],**pol},"report":json.loads(r.stdout)})
 data=json.dumps({"employers":sorted(entries,key=lambda x:x["employer"])})
 with tempfile.NamedTemporaryFile(mode="w",dir=dest.parent,delete=False) as f:f.write(data);name=f.name
 os.replace(name,dest)
except Exception:
 print("Invalid packet",file=sys.stderr);sys.exit(2)
'''
with tempfile.TemporaryDirectory(prefix="discovery-oracle-controls-",dir=a["workspace"]) as td:
 t=Path(td);w=t/"control-work";v=t/"control-peer";w.mkdir();v.mkdir()
 shutil.copytree(Path(a["workspace"])/"weekly-inputs",w/"weekly-inputs")
 shutil.copy2(Path(a["workspace"])/"intake_report.py",w/"intake_report.py")
 (w/"TEAM.json").write_text(json.dumps({"hostId":a["host"]}))
 for n,value in sc["POLICIES"].items():(v/("policy-weekly-"+n+".json")).write_text(json.dumps(value))
 script=w/"control.py";script.write_text(control_code)
 for path in [t,*t.rglob("*")]:
  os.chown(path,acct.pw_uid,acct.pw_gid);path.chmod(0o700 if path.is_dir() else 0o600)
 positive=sc["evaluate"](w,v,a["host"],a["linuxUser"],script)
 assert all(x["passed"] for x in positive),positive
 script.write_text('import json,sys\nfrom pathlib import Path\nPath(sys.argv[2]).write_text(json.dumps({"employers":[]}))\n')
 negative=sc["evaluate"](w,v,a["host"],a["linuxUser"],script)
 assert not all(x["passed"] for x in negative)
 (C/"oracle-controls.json").write_text(json.dumps({"at":time.time(),"mechanicalVerifierControlsOnly":True,"positive":positive,"constantOutputNegative":negative,"scope":"Not model evidence or production implementation; control workspace removed before activation."},indent=2)+"\n")
source_files=["prepare_goal_discovery_r234.py","goal_discovery_outcome_r234.py","run_goal_discovery_r234.py","freeze_goal_discovery_r234.py"]
paths=[*C.glob("*.txt"),C/"protocol.json",C/"participant-rubric.json",C/"outcome_scorer.py",C/"oracle-controls.json",*[Q/n for n in source_files]]
hashes={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in paths}
(C/"freeze.json").write_text(json.dumps({"at":time.time(),"hashes":hashes,"allFrozenBeforeNewModels":True,"noNewRuntimeDefault":True,"operatorOriginalRequestsAuthorized":1,"operatorEngineeringRequestsAuthorized":0,"peerWorkMustComeFromActualNativePeerRequest":True},indent=2)+"\n")
print(json.dumps({"frozen":str(C),"positivePassed":sum(x["passed"] for x in positive),"positiveTotal":len(positive),"constantOutputRejected":True,"newModels":0}))

