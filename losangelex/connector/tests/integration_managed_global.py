"""One actual Global room turn through the installed managed service and final API."""

import hashlib, json, os, secrets, socket, subprocess, time, urllib.request
from pathlib import Path
from uuid import uuid4
from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.store import Store, json_value
from lax_connector.host import enroll, resources
from lax_connector.linux_admin import provision
from lax_connector.journal import saved


def main():
    os.umask(0o077)
    assert os.geteuid() == 0 and socket.gethostname() == "ozzz-aosp"
    root = Path(os.environ["GLOBAL_LAUNCH_EVIDENCE"])
    root.mkdir(mode=0o700)
    runtime = Path(os.environ["GLOBAL_LAUNCH_RUNTIME"])
    python = str(runtime / "venv/bin/python")
    database = Path(os.environ["GLOBAL_LAUNCH_DATABASE_CONFIG"])
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 18772))
    initialize(
        json.loads(database.read_text()), root / "enterprise", "Managed Global launch"
    )
    setup = json.loads((root / "enterprise/installation-intent.json").read_text())
    owner = setup["credentials"]["Owner"]
    glob = setup["credentials"]["Global"]
    room = setup["globalRoomId"]
    host = str(uuid4())
    api = controller = None
    g = None
    store = None

    def call(method, path, body=None):
        req = urllib.request.Request(
            "http://127.0.0.1:18772/hollywood/v3/" + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + owner["token"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)

    def wait(read, accepted, seconds=300):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = read()
            if accepted(value):
                return value
            time.sleep(0.5)
        raise RuntimeError(
            "Original managed Global request did not settle; inspect it without replay"
        )

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

        def health():
            assert api.poll() is None
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:18772/health", timeout=2
                ) as response:
                    return response.status == 200
            except OSError:
                return False

        wait(health, bool, 30)
        g = provision(
            {
                "installationIntent": str(root / "enterprise/installation-intent.json"),
                "approvedModelAuthFile": os.environ["GLOBAL_LAUNCH_APPROVED_AUTH"],
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
            "POST",
            "placements",
            {
                "hostId": host,
                "name": "Managed Global host",
                "identityFingerprint": hashlib.sha256(
                    Path("/etc/machine-id").read_bytes()
                ).hexdigest(),
                "capabilities": {"managedGlobal": True},
                "agentId": g["agentId"],
            },
        )
        slots = resources()["cpuSlots"]
        enrollment = enroll(
            {
                "authorityId": setup["authorityId"],
                "hostId": host,
                "hollywoodUrl": "http://127.0.0.1:18772",
                "administratorCredential": owner,
                "policy": {
                    "maxConcurrent": slots,
                    "reservedInteractive": 1 if slots > 1 else 0,
                    "controlAgentIds": [g["agentId"]],
                    "memoryPerTurnBytes": 2 * 1024**3,
                    "reserveMemoryBytes": 4 * 1024**3,
                    "sampleMaxAgeSeconds": 30,
                    "connectorMaxAgeSeconds": 30,
                },
            }
        )
        saved(root / "host-enrollment.json", enrollment)
        with (root / "controller.log").open("wb") as log:
            controller = subprocess.Popen(
                [
                    python,
                    "-m",
                    "lax_connector.host",
                    "--serve",
                    enrollment["configPath"],
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        saved(
            root / "controller-process.json",
            {"pid": controller.pid, "providerTurns": 0},
        )
        marker = "MANAGED_GLOBAL_" + secrets.token_hex(12)
        body = {
            "operationId": "managed-global:" + str(uuid4()),
            "kind": "request",
            "recipientId": glob["principalId"],
            "audience": "room",
            "body": "Run one finite managed Global qualification. Confirm your actual ongoing native role using get_goal. Verify your installation administrator capability with sudo -n id -u, which must return 0. In your captured workspace write global-launch.txt containing exactly "
            + marker
            + " and newline, and verify the actual bytes. Read this Hollywood room's actual history. Then use hollywood_publish to publish exactly GLOBAL_LAUNCH_VERIFIED:"
            + marker
            + ". Do not provision other agents/rooms, create business goals, start schedules or other work. Finish this admitted turn and wait while keeping Global's ongoing role active.",
        }
        saved(root / "request-intent.json", body)
        receipt = call("POST", "rooms/" + room + "/messages", body)
        saved(root / "request-receipt.json", receipt)
        saved(
            root / "service-start-intent.json",
            {
                "unit": g["unit"],
                "authorityId": g["authorityId"],
                "maximumProviderTurns": 1,
                "historicalWorkResumed": False,
            },
        )
        subprocess.run(
            ["systemctl", "start", g["unit"]], capture_output=True, check=True
        )
        store = Store(json.loads(database.read_text()))

        def current():
            with store.pool.connection() as connection:
                return connection.execute(
                    "SELECT * FROM hb_delivery WHERE authority=%s",
                    (setup["authorityId"],),
                ).fetchall()

        ds = wait(
            current,
            lambda rows: (
                len(rows) == 1
                and rows[0]["state"] in ("completed", "failed", "unknown", "cancelled")
            ),
        )
        assert ds[0]["state"] == "completed"
        artifact = Path(g["home"]) / "work/global-launch.txt"
        assert artifact.read_bytes() == marker.encode() + bytes([10])
        with store.pool.connection() as connection:
            events = connection.execute(
                "SELECT body FROM hb_event WHERE authority=%s", (setup["authorityId"],)
            ).fetchall()
            bindings = connection.execute(
                "SELECT * FROM hb_native_goal_binding WHERE delivery=%s", (ds[0]["id"],)
            ).fetchall()
        assert any(
            event["body"] == "GLOBAL_LAUNCH_VERIFIED:" + marker for event in events
        )
        assert len(bindings) == 1
        assert store.delivery(g["agentId"], str(ds[0]["id"]))["nativeGoalBinding"]["binding_kind"] == "role"

        def executor():
            with store.pool.connection() as connection:
                return connection.execute(
                    "SELECT * FROM hb_executor WHERE delivery=%s", (ds[0]["id"],)
                ).fetchone()

        row = wait(executor, lambda value: value and value["state"] == "stopped", 45)
        state = Path(g["home"]) / "state"
        directory = state / "executions" / str(ds[0]["id"]) / str(ds[0]["generation"])
        assert (
            json.loads((directory / "native-admission-attestation.json").read_text())[
                "executor"
            ]["state"]
            == "live"
        )
        turns = []
        for path in (Path(g["home"]) / "codex-home/sessions").rglob("*.jsonl"):
            for line in path.read_text().splitlines():
                data = json.loads(line).get("payload", {})
                if data.get("type") == "task_started":
                    turns.append(data["turn_id"])
        assert turns == [ds[0]["native_turn"]]
        commands = [
            json.loads(path.read_text()).get("nativeItem", {})
            for path in state.glob("activity-*.json")
        ]
        assert any(
            item.get("type") == "commandExecution"
            and "sudo" in (item.get("command") or "")
            and "id -u" in (item.get("command") or "")
            and item.get("exitCode") == 0
            and "0" in (item.get("aggregatedOutput") or "").splitlines()
            for item in commands
        ), "Original native sudo execution/result was not observed"
        result = {
            "passed": True,
            "actualManagedGlobalProviderTurns": 1,
            "nativeContexts": 1,
            "roleBindingRetained": True,
            "nativeThread": ds[0]["native_thread"],
            "nativeTurn": ds[0]["native_turn"],
            "artifactSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "actualRoomCommunication": True,
            "registeredAndLiveBeforeInference": True,
            "resourceStoppedIndependently": True,
            "globalUnit": g["unit"],
            "globalNativeModelAdminCommandRequestedAndObserved": True,
            "originalUnknownControlJourneyQualified": False,
            "productionChanged": False,
            "physicalPhoneChanged": False,
        }
        saved(root / "result.json", result)
        print(json.dumps(result), flush=True)
    finally:
        errors = []
        if g:
            for args in [
                ["systemctl", "stop", g["unit"]],
                ["systemctl", "disable", g["unit"]],
            ]:
                value = subprocess.run(args, capture_output=True)
                if value.returncode:
                    errors.append("owned Global unit cleanup failed")
        for name, child in [("controller", controller), ("api", api)]:
            if child and child.poll() is None:
                try:
                    child.terminate()
                    child.wait(timeout=20)
                except Exception as error:
                    errors.append(name + ":" + type(error).__name__)
        owned = (
            []
            if g is None
            else subprocess.run(
                ["ps", "-u", str(g["uid"]), "-o", "pid=,comm="],
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
        saved(
            root / "cleanup.json",
            {
                "ownedGlobalProcesses": owned,
                "ownedApiStopped": api is None or api.poll() is not None,
                "ownedControllerStopped": controller is None
                or controller.poll() is not None,
                "cleanupErrors": errors,
                "productionChanged": False,
            },
        )
        if store:
            store.close()
        if errors or owned:
            raise RuntimeError("Owned managed Global cleanup remains unconfirmed")


if __name__ == "__main__":
    main()
