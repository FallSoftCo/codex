"""Actual managed native birth/attachment/resource tests; no provider submission."""

import hashlib
import json
import os
import pwd
import socket
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from uuid import uuid4

from hollywood_backbone.bootstrap import initialize
from lax_connector.connector import CAPABILITIES
from lax_connector.host import enroll, supervise
from lax_connector.journal import saved
from lax_connector.linux_admin import provision
from lax_connector.service_observer import register, properties

GUARDIAN = """import asyncio,json,os,sys
from pathlib import Path
from aiohttp import ClientSession
from lax_connector.connector import Connector
from lax_connector.execution_lifecycle import ExecutionLifecycle
from lax_connector.rpc import AppServer
from lax_connector.journal import saved
config=json.loads(Path(sys.argv[1]).read_text())
root=Path(config["state"])/"launch-qualification"
async def event(method,params):pass
async def request(method,params):raise RuntimeError("No native provider/tool request authorized")
async def flag(name):
 for _ in range(1600):
  if(root/name).exists():return
  await asyncio.sleep(.1)
 raise RuntimeError("Owned guardian control timeout")
async def main():
 c=Connector(config);c.active=json.loads((root/"claim.json").read_text())
 c.journal=c.executions.begin({"state":"captured-before-native","delivery":c.active["delivery"],"request":c.active["request"]})
 life=ExecutionLifecycle(c);rpc=None;helper=None
 async with ClientSession()as c.session:
  try:
   await life.prepare()
   saved(root/"registered.json",{"executorId":life.id,"providerTurns":0})
   if sys.argv[2]=="prebirth":
    await flag("finish");return
   rpc=AppServer(config["binary"],Path(config["codexHome"]),root/"native",event,request,on_spawn=life.attach)
   await rpc.start()
   helper=await asyncio.create_subprocess_exec("/usr/bin/sleep","140")
   saved(root/"native-ready.json",{"executorId":life.id,"nativePid":rpc.process.pid,"providerTurns":0})
   await flag("close-native");await rpc.close();saved(root/"native-closed.json",{"providerTurns":0})
   await flag("stop-helper");helper.terminate();await helper.wait();saved(root/"helper-stopped.json",{"providerTurns":0})
   await flag("finish")
  finally:
   if helper and helper.returncode is None:helper.terminate();await helper.wait()
   if rpc:await rpc.close()
asyncio.run(main())
"""


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and socket.gethostname() == "ozzz-aosp"
    root = Path(os.environ["LAUNCH_EVIDENCE"])
    root.mkdir(mode=0o700)
    runtime = Path(os.environ["LAUNCH_RUNTIME"])
    python = str(runtime / "venv/bin/python")
    database = Path(os.environ["LAUNCH_DATABASE_CONFIG"])
    case = os.environ["LAUNCH_CASE"]
    assert case in ("prebirth", "helper")
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 18772))
    initialize(
        json.loads(database.read_text()), root / "enterprise", "Native launch " + case
    )
    setup = json.loads((root / "enterprise/installation-intent.json").read_text())
    people = setup["credentials"]
    authority, room, host = setup["authorityId"], setup["globalRoomId"], str(uuid4())
    api = controller = None
    unit = None
    g = None

    def call(who, method, path, body=None, status=200):
        request = urllib.request.Request(
            "http://127.0.0.1:18772/hollywood/v3/" + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + people[who]["token"],
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                value, code = json.load(response), response.status
        except urllib.error.HTTPError as error:
            value, code = json.load(error), error.code
        assert code == status, (method, path, code, status)
        return value

    def wait(read, predicate=lambda value: bool(value), seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = read()
            if predicate(value):
                return value
            time.sleep(0.25)
        raise RuntimeError("Owned launch qualification did not settle")

    try:
        with (root / "api.log").open("wb") as log:
            api = subprocess.Popen(
                [
                    python,
                    "-m",
                    "hollywood_backbone.server",
                    "--database-config",
                    str(database),
                    "--port",
                    "18772",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )

        def healthy():
            assert api.poll() is None
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:18772/health", timeout=2
                ) as response:
                    return response.status == 200
            except OSError:
                return False

        wait(healthy)
        g = provision(
            {
                "installationIntent": str(root / "enterprise/installation-intent.json"),
                "approvedModelAuthFile": os.environ["LAUNCH_APPROVED_AUTH"],
                "binary": str(runtime / "native/bin/codex"),
                "interpreter": python,
                "hollywoodUrl": "http://127.0.0.1:18772",
                "hostId": host,
                "model": "gpt-6.1-sol",
                "effort": "xhigh",
            }
        )
        saved(root / "global-provision.json", g)
        call(
            "Owner",
            "POST",
            "placements",
            {
                "hostId": host,
                "name": "Owned native launch",
                "identityFingerprint": hashlib.sha256(
                    Path("/etc/machine-id").read_bytes()
                ).hexdigest(),
                "capabilities": {"nativeLax": True},
                "agentId": g["agentId"],
            },
        )
        enrolled = enroll(
            {
                "authorityId": authority,
                "hostId": host,
                "hollywoodUrl": "http://127.0.0.1:18772",
                "administratorCredential": people["Owner"],
                "policy": {
                    "maxConcurrent": 1,
                    "reservedInteractive": 0,
                    "controlAgentIds": [g["agentId"]],
                    "memoryPerTurnBytes": 1024**2,
                    "reserveMemoryBytes": 4 * 1024**3,
                    "sampleMaxAgeSeconds": 30,
                    "connectorMaxAgeSeconds": 30,
                },
            }
        )
        saved(root / "host-enrollment.json", enrolled)
        config = json.loads(Path(enrolled["configPath"]).read_text())
        supervise(config, once=True)
        source = call(
            "Owner",
            "POST",
            "rooms/" + room + "/messages",
            {
                "operationId": "launch-source:" + str(uuid4()),
                "kind": "request",
                "recipientId": g["agentId"],
                "body": "Explicit native process/resource qualification only; no model turn is authorized.",
            },
        )
        claim = call(
            "Global",
            "POST",
            "connector/claim",
            {
                "operationId": "launch-claim:" + str(uuid4()),
                "hostId": host,
                "capabilities": CAPABILITIES,
            },
        )
        assert claim["delivery"]
        saved(root / "original-claim.json", claim)
        local = Path(g["home"]) / "state/launch-qualification"
        local.mkdir(mode=0o700)
        os.chown(local, g["uid"], pwd.getpwnam(g["linuxUser"]).pw_gid)
        saved(local / "claim.json", claim)
        os.chown(local / "claim.json", g["uid"], pwd.getpwnam(g["linuxUser"]).pw_gid)
        script = runtime / ("qualification-launch-" + case + ".py")
        assert not script.exists()
        script.write_text(GUARDIAN)
        script.chmod(0o644)
        with (root / "controller.log").open("wb") as log:
            controller = subprocess.Popen(
                [python, "-m", "lax_connector.host", "--serve", enrolled["configPath"]],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        saved(
            root / "controller-process.json",
            {"pid": controller.pid, "modelsStarted": 0},
        )
        unit = "lax-launch-proof-" + authority.replace("-", "")[:12] + ".service"
        saved(
            root / "guardian-intent.json",
            {"unit": unit, "case": case, "modelTurnsAllowed": 0},
        )
        subprocess.run(
            [
                "systemd-run",
                "--unit=" + unit,
                "--uid=" + g["linuxUser"],
                "--property=KillMode=control-group",
                "--property=UMask=0077",
                "--property=MemoryMax=2G",
                "--property=RuntimeMaxSec=180",
                "--property=WorkingDirectory=" + g["home"] + "/work",
                python,
                str(script),
                g["connectorConfig"],
                case,
            ],
            capture_output=True,
            check=True,
        )
        wait(
            lambda: properties(unit),
            lambda value: (
                value["ActiveState"] == "active" and int(value["MainPID"]) > 1
            ),
        )
        saved(
            root / "service-registration.json",
            register(authority, host, g["agentId"], unit),
        )
        wait(lambda: (local / "registered.json").exists())
        executor = json.loads((local / "registered.json").read_text())["executorId"]
        reserved = call("Global", "GET", "executors/" + executor)
        assert reserved["executor"]["reservation_descriptor"]["nativePid"] is None
        saved(root / "reservation-observation.json", reserved)

        def row():
            return call("Global", "GET", "executors/" + executor)

        def flag(name):
            (local / name).write_text("one owned qualification control")

        if case == "prebirth":
            assert reserved["executor"]["launch_phase"] == "reserved"
            assert reserved["executor"]["state"] == "unknown"
            assert (
                reserved["executor"]["evidence"]["reason"]
                == "registered-launch-pending"
            )
            assert not (local / "native-ready.json").exists()
            subprocess.run(["systemctl", "stop", unit], check=True, capture_output=True)
            stopped = wait(row, lambda value: value["executor"]["state"] == "stopped")
            assert stopped["deliveryState"] == "unknown"
            saved(root / "prebirth-stop.json", stopped)
        else:
            wait(lambda: (local / "native-ready.json").exists())
            live = wait(row, lambda value: value["executor"]["state"] == "live")
            assert live["executor"]["launch_phase"] == "attached"
            saved(root / "native-live.json", live)
            call(
                "Global",
                "POST",
                "hosts/" + host + "/executors/" + executor + "/observation",
                {
                    "operationId": str(uuid4()),
                    "machineIdentity": config["machineIdentity"],
                    "descriptorDigest": live["executor"]["descriptor_digest"],
                    "state": "live",
                    "evidence": live["executor"]["evidence"],
                },
                403,
            )
            flag("close-native")
            wait(lambda: (local / "native-closed.json").exists())
            held = wait(
                row,
                lambda value: (
                    value["executor"]["state"] == "unknown"
                    and value["executor"]["evidence"]["reason"]
                    == "registered-unit-not-drained"
                ),
            )
            assert held["executor"]["evidence"]["remainingWorkProcessCount"] > 0
            saved(root / "helper-held.json", held)
            flag("stop-helper")
            wait(lambda: (local / "helper-stopped.json").exists())
            stopped = wait(row, lambda value: value["executor"]["state"] == "stopped")
            assert stopped["deliveryState"] == "unknown"
            saved(root / "native-stopped.json", stopped)
            call(
                "Global",
                "POST",
                "executors/" + executor + "/native",
                {
                    "operationId": "late-attach:" + str(uuid4()),
                    "hostId": host,
                    "generation": claim["delivery"]["generation"],
                    "claimId": claim["delivery"]["claim_id"],
                    "reservationDigest": stopped["executor"]["reservation_digest"],
                    "nativePid": stopped["executor"]["descriptor"]["nativePid"],
                    "nativeStart": stopped["executor"]["descriptor"]["nativeStart"],
                },
                409,
            )
            flag("finish")
        result = {
            "passed": True,
            "case": case,
            "actualNativeAppServer": case == "helper",
            "actualManagedGuardian": True,
            "independentController": True,
            "providerTurns": 0,
            "prebirthReservationPreserved": True,
            "unknownEffectsRetained": True,
            "agentCannotAttestOwnStop": case == "helper",
            "productionChanged": False,
            "physicalPhoneChanged": False,
        }
        saved(root / "result.json", result)
        print(json.dumps(result), flush=True)
    finally:
        errors = []
        if unit:
            stop = subprocess.run(["systemctl", "stop", unit], capture_output=True)
            if stop.returncode:
                status = subprocess.run(["systemctl", "show", unit, "-p", "LoadState", "-p", "ActiveState"], capture_output=True, text=True).stdout
                if "LoadState=not-found" not in status and "ActiveState=inactive" not in status:
                    errors.append("guardian stop unconfirmed")
        for name, child in (("controller", controller), ("api", api)):
            if child and child.poll() is None:
                try:
                    child.terminate()
                    child.wait(timeout=20)
                except Exception as error:
                    errors.append(name + ":" + type(error).__name__)
        owned = [] if g is None else subprocess.run(
            ["ps", "-u", str(g["uid"]), "-o", "pid=,comm="],
            capture_output=True, text=True,
        ).stdout.splitlines()
        saved(root / "cleanup.json", {
            "ownedGuardianProcesses": owned,
            "ownedApiStopped": api is None or api.poll() is not None,
            "ownedControllerStopped": controller is None or controller.poll() is not None,
            "cleanupErrors": errors, "providerTurns": 0,
        })
        if errors or owned:
            raise RuntimeError("Owned launch qualification cleanup remains unconfirmed")


if __name__ == "__main__":
    main()
