"""Owned native installation restart integration, with real durable contexts.

Explicit --exercise-owned-stop is required. This is not an automatic unit test.
No task/model submissions are permitted. The operator supplies a new idle scope.
"""
import argparse,json,subprocess,time,hashlib
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

a=argparse.ArgumentParser()
a.add_argument("--deployment",type=Path,required=True)
a.add_argument("--database-config",type=Path,required=True)
a.add_argument("--installer",required=True)
a.add_argument("--exercise-owned-stop",action="store_true",required=True)
args=a.parse_args();root=args.deployment;proof=root/"startup-lifecycle-r89.json"
assert not proof.exists() and not (root/"startup-lifecycle-intent-r89.json").exists(),"Inspect original test without replay"
setup=json.loads((root/"bootstrap/installation-intent.json").read_text())
authority=setup["authorityId"];agent=setup["credentials"]["Global"]["principalId"]
record=Path("/var/lib/harness")/authority/"purpose-agents"/agent
manifest=json.loads((record/"installation.json").read_text())
config=json.loads(Path(manifest["config"]).read_text())
startup=json.loads((root/"startup-preparation-r87.json").read_text())["result"]["startup"]
members=startup["members"]
protected=["harness-postgres.service","hollywood-backbone.service","nextcomp-native-core.service"]
assert not set(members)&set(protected) and len(members)==7

def props(unit):
 return dict(x.split("=",1) for x in subprocess.check_output(
  ["systemctl","show",unit,"-p","MainPID","-p","ActiveState"],text=True).splitlines())
def cli(*flags):
 p=subprocess.run([args.installer,"--spec",str(root/"native-profile.json"),*flags],capture_output=True,text=True)
 if p.returncode:raise RuntimeError(p.stderr[-2500:])
 return json.loads(p.stdout)
def durable():
 with psycopg.connect(**json.loads(args.database_config.read_text()),row_factory=dict_row) as c:
  threads=c.execute("SELECT purpose,context_id,native_thread FROM hb_purpose_context WHERE agent=%s ORDER BY purpose",(agent,)).fetchall()
  permits=c.execute("SELECT count(*) n FROM hb_context_permit WHERE agent=%s",(agent,)).fetchone()["n"]
  deliveries=c.execute("SELECT id,state,result_event,generation,claim_id,native_thread,native_turn FROM hb_delivery WHERE authority=%s ORDER BY id",(authority,)).fetchall()
  c.rollback()
 return json.loads(json.dumps({"threads":threads,"permits":permits,"deliveries":deliveries},default=str))
def idle(after=0):
 for purpose in manifest["units"]:
  d=json.loads((Path(config["state"])/("status-"+purpose+".json")).read_text())
  s=d["contexts"][purpose]
  if d["at"]<=after or time.time()-d["at"]>5 or s["active"] or s["held"] or s["pending"]:return False
 return True

before={u:props(u) for u in members};protected_before={u:props(u) for u in protected};logical=durable()
assert all(s["ActiveState"]=="active" for s in before.values()) and idle()
assert len(logical["threads"])==3 and len({s["native_thread"] for s in logical["threads"]})==3
assert all(s["state"] in ["completed","cancelled","failed"] for s in logical["deliveries"])
import sqlite3
with sqlite3.connect(root/"nextcomp/pocket.sqlite") as c:
 assert c.execute("SELECT count(*) FROM devices").fetchone()[0]==1,"A real app paired; obtain a fresh client boundary"
 assert c.execute("SELECT count(*) FROM voice_turns WHERE state IN ('thinking','transcribing')").fetchone()[0]==0
assert not Path("/proc/"+before["nextcomp-native-pilot-20261019-r01.service"]["MainPID"]+"/task/"+before["nextcomp-native-pilot-20261019-r01.service"]["MainPID"]+"/children").read_text().strip()
(root/"startup-lifecycle-intent-r89.json").write_text(json.dumps({"at":time.time(),"scope":members,"before":before,"logical":logical,"noWorkSubmissions":True,"steps":["Default reconcile preserves disabled boot and PIDs","Explicit enable/disable changes boot only","Reconcile preserves one deliberate stopped purpose","Start exact owned target after owned cold stop; same histories/receipts and no inference"]},indent=2)+"\n")
assert cli()["startup"]["bootState"]=="disabled"
assert {u:props(u) for u in members}==before
assert cli("--enable-startup")["startup"]["bootState"]=="enabled"
assert {u:props(u) for u in members}==before
assert cli("--disable-startup")["startup"]["bootState"]=="disabled"
responder=manifest["units"]["responder"]
subprocess.run(["systemctl","stop",responder],check=True,capture_output=True)
r=cli("--activate")
assert props(responder)["ActiveState"]=="inactive" and r["startup"]["bootState"]=="disabled"
assert all(props(u)==before[u] for u in members if u!=responder)
print(json.dumps({"phase":"reconcile-preserved-explicit-boot-disable-and-responder-stop"}),flush=True)
# These are only the exact idle test members recorded above, never shared DB/production.
assert idle() and durable()==logical
subprocess.run(["systemctl","stop",*members],check=True,capture_output=True)
assert all(props(u)["ActiveState"]=="inactive" for u in members)
started=time.time()
subprocess.run(["systemctl","start",startup["unit"]],check=True,capture_output=True)
deadline=time.monotonic()+60
while True:
 states={u:props(u) for u in members}
 if all(s["ActiveState"]=="active" for s in states.values()) and idle(started):break
 if time.monotonic()>deadline:raise RuntimeError("Original owned startup did not recover; inspect same units and intent")
 time.sleep(.5)
assert durable()==logical,"Native inference or durable identity changed; inspect exact receipts"
assert {u:props(u) for u in protected}==protected_before
assert cli()["startup"]["bootState"]=="disabled"
assert cli("--enable-startup")["startup"]["bootState"]=="enabled"
result={"schema":"native-owned-startup-integration/v1","at":time.time(),"authority":authority,"agent":agent,"startupUnit":startup["unit"],"members":members,"beforePids":before,"afterPids":states,"protectedPidsUnchanged":protected_before,"sameThreeNativeHistories":logical["threads"],"sameOriginalDeliveryReceipts":logical["deliveries"],"nativeInferencePermitsBeforeAndAfter":logical["permits"],"noInferenceOrTaskReplay":True,"defaultReconcilePreservesBootDisable":True,"defaultReconcilePreservesDeliberatePurposeStop":True,"explicitTargetStartRecoveredOwnedColdCohort":True,"finalBootState":"enabled","databaseRestarted":False,"actualHostRebootTested":False,"limits":"Owned idle installation restart only; no physical phone/FCM/provider voice, host reboot, shared PostgreSQL restart or cross-host acceptance implied."}
proof.write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps({k:v for k,v in result.items() if k not in ["beforePids","afterPids","sameThreeNativeHistories","sameOriginalDeliveryReceipts"]},indent=2))
