"""Upgrade original native role receipts and metadata without another model turn."""

import argparse
import asyncio
import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from hollywood_backbone.store import Store
from lax_connector.journal import saved

NATIVE_READ = """
import asyncio,json,sys
from pathlib import Path
from lax_connector.rpc import AppServer
from lax_connector.native_goals import external_admission
async def main():
 spec=json.load(sys.stdin)
 config=json.loads(Path(spec["config"]).read_text())
 async def unexpected(*args):
  raise RuntimeError("Metadata verification cannot receive execution requests")
 async def event(method,params):
  if method=="turn/started":
   raise RuntimeError("Metadata verification unexpectedly started execution")
 rpc=AppServer(config["binary"],Path(config["codexHome"]),Path(config["state"])/"native",event,unexpected)
 out=[]
 try:
  await rpc.start()
  await external_admission(rpc,spec["role"])
  for binding in spec["bindings"]:
   thread=binding["native_thread"]
   goal=await rpc.call("thread/goal/get",{"threadId":thread})
   history=await rpc.call("thread/read",{"threadId":thread,"includeTurns":True})
   assert goal["goalId"]==binding["native_goal_id"]
   assert hashlib.sha256(goal["goal"]["objective"].encode()).hexdigest()==binding["objective_digest"]
   turns=history["thread"]["turns"]
   out.append({"threadId":thread,"nativeGoalId":goal["goalId"],"goalStatus":goal["goal"]["status"],"tokensUsed":goal["goal"]["tokensUsed"],"turnIds":[t["id"] for t in turns]})
 finally:
  await rpc.close()
 print(json.dumps(out))
import hashlib
asyncio.run(main())
"""


def main(spec):
    os.umask(0o077)
    root, previous = Path(spec["evidence"]), Path(spec["previousCase"])
    root.mkdir(mode=0o700)
    saved(root / "intent.json", {**spec, "modelsAuthorized": 0})
    prior = json.loads((previous / "result.json").read_text())
    assert prior["state"] == "passed-real-native-role-and-business-goals"
    cleanup = json.loads((previous / "cleanup.json").read_text())
    for unit in [
        cleanup["globalUnitStopped"],
        *cleanup["workerUnitsStoppedAndDisabled"],
    ]:
        assert (
            subprocess.check_output(
                ["systemctl", "show", unit, "-p", "ActiveState", "--value"], text=True
            ).strip()
            == "inactive"
        )
    installation = json.loads(
        (previous / "enterprise/installation-intent.json").read_text()
    )
    owner = installation["credentials"]["Owner"]
    authority = installation["authorityId"]
    with socket.socket() as check:
        check.bind(("127.0.0.1", spec["port"]))
    store = Store(json.loads(Path(spec["databaseConfig"]).read_text()))
    api = None
    native = []
    try:
        store.migrate()
        with store.pool.connection() as c:
            columns = c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='hb_native_goal_binding' ORDER BY ordinal_position"
            ).fetchall()
            assert len(columns) == 10
            rows = c.execute(
                "SELECT id FROM hb_delivery WHERE authority=%s ORDER BY id",
                (authority,),
            ).fetchall()
        deliveries = [store.delivery(owner["principalId"], str(r["id"])) for r in rows]
        assert len(deliveries) == prior["realNativeTurns"]
        assert all(
            d["delivery"]["state"] in ("completed", "cancelled") for d in deliveries
        )
        by_agent = {}
        for d in deliveries:
            binding = d["nativeGoalBinding"]
            by_agent.setdefault(d["delivery"]["agent"], {})[
                binding["native_thread"]
            ] = binding
        assert sorted(len(v) for v in by_agent.values()) == [1, 2]
        global_receipt = json.loads(
            (previous / "global-provision-receipt.json").read_text()
        )
        workers = [
            json.loads(p.read_text())
            for p in (Path("/var/lib/harness") / authority / "workers").glob(
                "*/provision-receipt.json"
            )
        ]
        for receipt in [global_receipt, *workers]:
            config_path = receipt.get("connectorConfig") or str(
                Path(receipt["workspace"]).parent / "connector.json"
            )
            config = json.loads(Path(config_path).read_text())
            bindings = list(by_agent[config["agentId"]].values())
            child = subprocess.run(
                [
                    "runuser",
                    "-u",
                    receipt["linuxUser"],
                    "--",
                    spec["runtime"] + "/venv/bin/python",
                    "-c",
                    NATIVE_READ,
                ],
                input=json.dumps(
                    {
                        "config": config_path,
                        "role": receipt is global_receipt,
                        "bindings": bindings,
                    }
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=config["workspace"],
                timeout=90,
            )
            saved(
                root / ("native-read-" + config["agentId"] + ".json"),
                {
                    "returncode": child.returncode,
                    "stdout": child.stdout,
                    "stderr": child.stderr,
                },
            )
            assert child.returncode == 0, "Original native metadata read failed"
            native.extend(json.loads(child.stdout))
        assert sorted(r["goalStatus"] for r in native) == [
            "active",
            "complete",
            "paused",
        ]
        assert sum(len(r["turnIds"]) for r in native) == prior["realNativeTurns"]
        python = spec["runtime"] + "/venv/bin/python"
        log = (root / "api.log").open("ab")
        api = subprocess.Popen(
            [
                "runuser",
                "-u",
                "aosp",
                "--",
                python,
                "-m",
                "hollywood_backbone.server",
                "--database-config",
                spec["databaseConfig"],
                "--port",
                str(spec["port"]),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        base = "http://127.0.0.1:" + str(spec["port"])
        for _ in range(80):
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Metadata upgrade API did not become healthy")
        assert (
            json.loads(Path(global_receipt["connectorConfig"]).read_text())[
                "hollywoodUrl"
            ]
            == base
        )
        state = Path(global_receipt["home"]) / "state"
        for name in ("claim-intent.json", "claim-receipt.json", "execution.json"):
            saved(root / ("before-" + name), json.loads((state / name).read_text()))
        idle = subprocess.run(
            [
                "runuser",
                "-u",
                global_receipt["linuxUser"],
                "--",
                python,
                "-m",
                "lax_connector.connector",
                "--config",
                global_receipt["connectorConfig"],
                "--claim-id",
                "role-upgrade-empty-qualification",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            cwd=global_receipt["home"] + "/work",
        )
        saved(
            root / "cold-client-result.json",
            {
                "returncode": idle.returncode,
                "stdout": idle.stdout,
                "stderr": idle.stderr,
            },
        )
        assert idle.returncode == 0
        assert json.loads(idle.stdout) == {"state": "idle", "modelsStarted": 0}
        for before in deliveries:
            after = store.delivery(owner["principalId"], before["delivery"]["id"])
            assert after == before
        assert json.loads((state / "execution.json").read_text()) == json.loads(
            (root / "before-execution.json").read_text()
        )
        result = {
            "state": "passed-original-native-role-upgrade",
            "authorityId": authority,
            "legacyBindingColumns": 10,
            "originalDeliveriesUnchanged": len(deliveries),
            "nativeGoalInstancesUnchanged": 3,
            "nativeTurnsRetained": sum(len(r["turnIds"]) for r in native),
            "newModelTurns": 0,
            "globalRoleActive": True,
            "workerGoalsCompleteAndPaused": True,
            "newClientAuthenticatedIdleAdmission": True,
            "agentServicesResumed": False,
            "productionChanged": False,
            "physicalPhone": False,
            "nativeMetadata": native,
        }
        saved(root / "result.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "nativeMetadata"}))
    finally:
        if api and api.poll() is None:
            api.terminate()
            api.wait(timeout=20)
        store.close()
        saved(
            root / "cleanup.json",
            {
                "apiStopped": True,
                "agentServicesResumed": False,
                "productionChanged": False,
            },
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    main(json.loads(parser.parse_args().spec.read_text()))
