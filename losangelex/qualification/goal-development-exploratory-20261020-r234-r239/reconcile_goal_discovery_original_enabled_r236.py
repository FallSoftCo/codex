import importlib.util,json,subprocess,time
from pathlib import Path
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
sp=importlib.util.spec_from_file_location("m",Q/"run_goal_definition_r228.py");m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
C=m.ROOT/"goal-discovery-r234";p=json.loads((C/"protocol.json").read_text());b=p["actors"]["engineer"];cfg=json.loads(Path(b["config"]).read_text());state=Path(cfg["state"])/"writer"
secret=json.loads((m.ROOT/"ordinary/installation-intent.json").read_text())
api=lambda method,path,body=None:m.request("http://127.0.0.1:18783",secret["credentials"]["Owner"]["token"],method,path,body)
assert all(m.pid(u)=="0" for a in p["actors"].values() for u in a["units"].values())
assert not (C/"reconcile-enabled-original-intent-r236.json").exists()
before=m.h.usage(cfg,"three");row=api("GET","placements/"+b["agent"]);assert row["state"]=="paused"
m.saved(C/"reconcile-enabled-original-intent-r236.json",{"at":time.time(),"scope":"Only temporarily enable this QA peer placement for existing receipt settlement. All normal units remain stopped; one existing --reconcile-only utility may observe/end the exact original turn. No inference, callback replay or new work.","placementBefore":row,"usageBefore":before,"knownGap":"context_system.action currently requires enabled placement even for end; pause can block terminal settlement. Record separate architecture issue, don't change production or infer task success."})
m.administrative_put(C,api,"placements/"+b["agent"],{"operationId":"goal-discovery-r236:receipt-reconcile-enable","hostId":b["host"],"revision":row["placement"]["revision"],"enabled":True})
try:
 command=["systemd-run","--unit=lax-qa-original-writer-reconcile-r236b.service","--wait","--collect","-p","User="+b["linuxUser"],"-p","WorkingDirectory="+b["workspace"],"-p","RuntimeMaxSec=90","-p","MemoryMax=2147483648","-p","CPUQuota=100%","--","/opt/lax-three-context-20261018-r01/venv-r212/bin/python","-I","-B","-m","lax_connector.context_runtime","--config",b["config"],"--purpose","writer","--reconcile-only"]
 r=subprocess.run(command,capture_output=True,text=True,timeout=110)
 after=m.h.usage(cfg,"three")
 m.saved(C/"reconcile-enabled-original-result-r236.json",{"at":time.time(),"exitCode":r.returncode,"stderr":r.stderr[-2000:],"nativeUsageUnchanged":after["total_tokens"]==before["total_tokens"],"wakeAfter":json.loads((state/"wake.json").read_text()),"normalUnitPids":{u:m.pid(u) for a in p["actors"].values() for u in a["units"].values()},"originalTaskRemainsCancelled":api("GET","deliveries/c86c02df-e05d-4325-8c86-befc3aed2d21")["delivery"]["state"]=="cancelled"})
 print(json.dumps({"exitCode":r.returncode,"nativeUsageUnchanged":after["total_tokens"]==before["total_tokens"],"wakeAfter":json.loads((state/"wake.json").read_text())}),flush=True)
finally:
 row=api("GET","placements/"+b["agent"])
 m.administrative_put(C,api,"placements/"+b["agent"],{"operationId":"goal-discovery-r236:receipt-reconcile-pause","hostId":b["host"],"revision":row["placement"]["revision"],"enabled":False})

