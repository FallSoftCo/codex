import importlib.util,json,subprocess,time
from pathlib import Path
Q=Path("/aosp/development/lax-three-context-20261018-r01/qualification")
sp=importlib.util.spec_from_file_location("m",Q/"run_goal_definition_r228.py");m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
C=m.ROOT/"goal-discovery-r234";p=json.loads((C/"protocol.json").read_text());b=p["actors"]["engineer"];cfg=json.loads(Path(b["config"]).read_text());state=Path(cfg["state"])/"writer"
assert m.pid(b["units"]["writer"])=="0";assert not (C/"reconcile-original-writer-intent-r236.json").exists()
intent={"at":time.time(),"action":"existing shipped --reconcile-only,writer","modelInferenceAuthorized":False,"nativeCallbackReplayAuthorized":False,"originalWake":json.loads((state/"wake.json").read_text()),"nativeUsageBefore":m.h.usage(cfg,"three"),"source":"context_runtime.py:start observes original_turn; serve(reconcile_only=True) returns before scheduling; placement remains paused."}
m.saved(C/"reconcile-original-writer-intent-r236.json",intent)
command=["systemd-run","--unit=lax-qa-original-writer-reconcile-r236.service","--wait","--collect","-p","User="+b["linuxUser"],"-p","WorkingDirectory="+b["workspace"],"-p","RuntimeMaxSec=90","-p","MemoryMax=2147483648","-p","CPUQuota=100%","--","/opt/lax-three-context-20261018-r01/venv-r212/bin/python","-I","-B","-m","lax_connector.context_runtime","--config",b["config"],"--purpose","writer","--reconcile-only"]
r=subprocess.run(command,capture_output=True,text=True,timeout=110)
after=m.h.usage(cfg,"three")
out={"at":time.time(),"exitCode":r.returncode,"stdout":r.stdout[-2000:],"stderr":r.stderr[-3000:],"nativeUsageUnchanged":after["total_tokens"]==intent["nativeUsageBefore"]["total_tokens"],"wakeAfter":json.loads((state/"wake.json").read_text()),"reconciliation":json.loads((Path(cfg["state"])/"reconciliation-writer.json").read_text()) if (Path(cfg["state"])/"reconciliation-writer.json").exists() else None}
m.saved(C/"reconcile-original-writer-result-r236.json",out)
print(json.dumps(out),flush=True)

