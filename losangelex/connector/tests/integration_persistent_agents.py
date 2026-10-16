"""Real installed-agent journey: identity continuity, room participation and peer completion."""

import argparse, hashlib, json, os, secrets, socket, subprocess, time, urllib.error, urllib.request
from pathlib import Path
from uuid import uuid4

from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.store import Store, digest, json_value
from lax_connector.host import enroll, resources
from lax_connector.linux_admin import provision
from lax_connector.journal import saved


def main(spec):
    os.umask(0o077)
    assert os.geteuid() == 0 and socket.gethostname() == "ozzz-aosp"
    root = Path(spec["evidence"])
    root.mkdir(mode=0o700, exist_ok=True)
    runtime = Path(spec["runtime"])
    python = str(runtime / "venv/bin/python")
    setup_path = root / "enterprise/installation-intent.json"
    initialize(
        json.loads(Path(spec["databaseConfig"]).read_text()),
        root / "enterprise",
        "Persistent agent journey",
    )
    setup = json.loads(setup_path.read_text())
    owner = setup["credentials"]["Owner"]
    glob = setup["credentials"]["Global"]
    room = setup["globalRoomId"]
    authority = setup["authorityId"]
    store = Store(json.loads(Path(spec["databaseConfig"]).read_text()))
    marker_path = root / "scenario.json"
    if not marker_path.exists():
        saved(
            marker_path,
            {"host": str(uuid4()), "marker": "PERSISTENT_" + secrets.token_hex(12)},
        )
    scenario = json.loads(marker_path.read_text())
    host = scenario["host"]
    marker = scenario["marker"]
    port = spec["port"]
    url = "http://127.0.0.1:" + str(port)
    api = controller = None
    global_receipt = None
    errors = []

    def call(method, path, body=None, credential=None):
        token = (credential or owner)["token"]
        request = urllib.request.Request(
            url + "/hollywood/v3/" + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def post_once(label, path, body, credential=None):
        receipt = root / (label + "-receipt.json")
        intent = root / (label + "-intent.json")
        if receipt.exists():
            return json.loads(receipt.read_text())
        if intent.exists():
            result = call(
                "GET", "commands/" + body["operationId"], credential=credential
            )
        else:
            saved(intent, {"path": path, "body": body})
            result = call("POST", path, body, credential=credential)
        saved(receipt, result)
        return result

    def wait(label, read, predicate, seconds=360):
        end = time.monotonic() + seconds
        last = None
        while time.monotonic() < end:
            if api and api.poll() is not None:
                raise RuntimeError("Owned API ended")
            last = read()
            if predicate(last):
                return last
            time.sleep(0.5)
        saved(root / ("timeout-" + label + ".json"), json_value(last))
        raise TimeoutError(label + "; original operations retained, no resubmission")

    def rows():
        with store.pool.connection() as c:
            return json_value(
                c.execute(
                    "SELECT d.*,e.body,e.data,e.room FROM hb_delivery d JOIN hb_event e ON e.id=d.event WHERE d.authority=%s ORDER BY e.seq",
                    (authority,),
                ).fetchall()
            )

    def stop_owned():
        units = []
        p = Path("/var/lib/harness") / authority
        for file in (p / "workers").glob("*/provision-receipt.json"):
            units.append(json.loads(file.read_text())["unit"])
        if global_receipt:
            units.append(global_receipt["unit"])
        for unit in units:
            for command in ["stop", "disable"]:
                r = subprocess.run(
                    ["systemctl", command, unit], capture_output=True, timeout=45
                )
                if r.returncode:
                    errors.append(unit + ":" + command)
        return units

    try:
        with (root / "api.log").open("ab") as log:
            api = subprocess.Popen(
                [
                    python,
                    "-m",
                    "hollywood_backbone.server",
                    "--database-config",
                    spec["databaseConfig"],
                    "--port",
                    str(port),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        saved(
            root / "api-process.json",
            {"pid": api.pid, "port": port, "privateLoopback": True},
        )

        def healthy():
            try:
                with urllib.request.urlopen(url + "/health", timeout=2) as r:
                    return r.status == 200
            except OSError:
                return False

        wait("health", healthy, bool, 30)
        global_receipt = provision(
            {
                "installationIntent": str(setup_path),
                "approvedModelAuthFile": spec["approvedModelAuthFile"],
                "binary": str(runtime / "native/bin/codex"),
                "interpreter": python,
                "hollywoodUrl": url,
                "hostId": host,
                "model": "gpt-6.1-sol",
                "effort": "xhigh",
            }
        )
        saved(root / "global-provision.json", global_receipt)
        call(
            "POST",
            "placements",
            {
                "hostId": host,
                "name": "Persistent agent qualification",
                "identityFingerprint": hashlib.sha256(
                    Path("/etc/machine-id").read_bytes()
                ).hexdigest(),
                "capabilities": {"qualification": True},
                "agentId": glob["principalId"],
            },
        )
        host_receipt = enroll(
            {
                "authorityId": authority,
                "hostId": host,
                "hollywoodUrl": url,
                "administratorCredential": owner,
                "policy": {
                    "maxConcurrent": min(resources()["cpuSlots"], 4),
                    "reservedInteractive": 1,
                    "controlAgentIds": [glob["principalId"]],
                    "memoryPerTurnBytes": 2 * 1024**3,
                    "reserveMemoryBytes": 4 * 1024**3,
                    "sampleMaxAgeSeconds": 30,
                    "connectorMaxAgeSeconds": 30,
                },
            }
        )
        saved(root / "host-enrollment.json", host_receipt)
        with (root / "controller.log").open("ab") as log:
            controller = subprocess.Popen(
                [
                    python,
                    "-m",
                    "lax_connector.host",
                    "--serve",
                    host_receipt["configPath"],
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        saved(root / "controller-process.json", {"pid": controller.pid})
        first = {
            "operationId": "persistent-first-" + authority,
            "kind": "request",
            "recipientId": glob["principalId"],
            "audience": "room",
            "body": "For this disposable enterprise, build and independently review a tiny installation proof. "
            "Verify your actual host administrator access with sudo -n id -u. Write enterprise-proof.txt in your workspace "
            "containing the line "
            + marker
            + " and the actual host identity. Create one agent named Workshop peer, with the "
            "responsibility of independently reviewing that artifact, and one room named Workshop owned by that agent. "
            "Give the peer read/post/request membership in this Global room too, establish its home room, and provision it. "
            "Send it one request in Workshop to independently read your artifact using the explicit same-host artifact location, "
            "write its own peer-review.txt with the marker and a verified SHA256, and return its result. Publish a passive update "
            "in Workshop. When its completion arrives, inspect the actual peer evidence, write accepted-proof.txt in your "
            "workspace containing the original marker and the verified artifact references, and publish the acceptance in this "
            "Global room. Use no other agents or business services. Do not alter product work, accounts, schedules, or production. "
            "Do not wait by polling a model. Preserve the unfinished review responsibility until the peer result is accounted for.",
        }
        first_result = post_once("first", "rooms/" + room + "/messages", first)
        subprocess.run(
            ["systemctl", "start", global_receipt["unit"]],
            check=True,
            capture_output=True,
        )

        def phase1_complete(v):
            if any(r["state"] in ("failed", "unknown", "cancelled") for r in v):
                raise RuntimeError(
                    "Original native journey has a failed/unknown result; inspect without replay"
                )
            return len(v) >= 3 and all(r["state"] == "completed" for r in v)

        first_rows = wait("delegation-and-review", rows, phase1_complete, 600)
        assert len(first_rows) == 3, first_rows
        with store.pool.connection() as c:
            contexts = json_value(
                c.execute(
                    "SELECT * FROM hb_agent_context WHERE authority=%s", (authority,)
                ).fetchall()
            )
            goal_count = c.execute(
                "SELECT count(*) AS n FROM hb_native_goal_binding WHERE delivery=ANY(%s)",
                ([r["id"] for r in first_rows],),
            ).fetchone()["n"]
            agents = json_value(
                c.execute(
                    "SELECT * FROM hb_principal WHERE authority=%s AND kind='agent'",
                    (authority,),
                ).fetchall()
            )
        assert len(contexts) == 2 and goal_count == 0
        peer = next(a for a in agents if a["id"] != glob["principalId"])
        peer_provision = json.loads(
            (
                Path("/var/lib/harness")
                / authority
                / "workers"
                / peer["id"]
                / "provision-receipt.json"
            ).read_text()
        )
        workshop = call("GET", "agents/" + peer["id"] + "/role")["home_room"]
        proof = Path(global_receipt["home"]) / "work/accepted-proof.txt"
        assert marker in proof.read_text()
        peer_artifact = Path(peer_provision["workspace"]) / "peer-review.txt"
        assert marker in peer_artifact.read_text()
        assert {r["room"] for r in first_rows if r["agent"] == glob["principalId"]} == {
            room,
            workshop,
        }
        saved(
            root / "phase1-result.json",
            {
                "passed": True,
                "deliveries": first_rows,
                "contexts": contexts,
                "globalAcceptedArtifact": str(proof),
                "peerArtifact": str(peer_artifact),
                "nativeSyntheticGoals": goal_count,
            },
        )

        # Restart only the owned disposable Global; a second human uses another room.
        old_pid = subprocess.check_output(
            ["systemctl", "show", global_receipt["unit"], "-p", "MainPID", "--value"],
            text=True,
        ).strip()
        subprocess.run(
            ["systemctl", "restart", global_receipt["unit"]],
            check=True,
            capture_output=True,
        )
        second_path = root / "second-human.json"
        if not second_path.exists():
            saved(
                second_path,
                {"principalId": str(uuid4()), "token": secrets.token_urlsafe(40)},
            )
        second = json.loads(second_path.read_text())
        call(
            "POST",
            "principals",
            {
                "id": second["principalId"],
                "name": "Second human",
                "kind": "human",
                "enrollmentCredential": second["token"],
            },
        )
        call(
            "PUT",
            "rooms/" + workshop + "/membership",
            {
                "principalId": second["principalId"],
                "can_read": True,
                "can_post": True,
                "can_request": True,
                "revision": 0,
            },
        )
        post_once(
            "second-human",
            "rooms/" + workshop + "/messages",
            {
                "operationId": "persistent-second-" + authority,
                "kind": "request",
                "recipientId": glob["principalId"],
                "audience": "room",
                "body": "Continue the installation proof you just accepted. In your workspace write resumed-proof.txt containing the "
                "original proof marker and the Workshop peer's artifact SHA256, using your existing context and evidence. "
                "Publish a concise result here. This is a follow-up from a second authorized human, not a new enterprise.",
            },
            second,
        )
        second_rows = wait(
            "second-human-after-restart",
            rows,
            lambda v: len(v) == 4 and all(r["state"] == "completed" for r in v),
        )
        resumed = Path(global_receipt["home"]) / "work/resumed-proof.txt"
        assert marker in resumed.read_text()
        new_pid = subprocess.check_output(
            ["systemctl", "show", global_receipt["unit"], "-p", "MainPID", "--value"],
            text=True,
        ).strip()
        assert new_pid != old_pid
        assert (
            len(
                {
                    r["native_thread"]
                    for r in second_rows
                    if r["agent"] == glob["principalId"]
                }
            )
            == 1
        )

        # Pending work survives an idle responsibility/home-room change.
        subprocess.run(
            ["systemctl", "stop", peer_provision["unit"]],
            check=True,
            capture_output=True,
        )
        post_once(
            "pending-before-role",
            "rooms/" + room + "/messages",
            {
                "operationId": "persistent-role-" + authority,
                "kind": "request",
                "recipientId": peer["id"],
                "audience": "room",
                "body": "Continue your earlier independent review. Read your current responsibility and write role-continuity.txt "
                "in your workspace containing the original proof marker, current primary role, home room ID and role revision. "
                "This queued request must remain yours through the authorized responsibility change.",
            },
        )
        role = call("GET", "agents/" + peer["id"] + "/role")
        role_result = call(
            "PUT",
            "agents/" + peer["id"] + "/role",
            {
                "operationId": "role-change-" + authority,
                "primary": "maintainer",
                "purpose": "Maintain the already reviewed proof and its continuity.",
                "homeRoomId": room,
                "revision": role["revision"],
            },
        )
        saved(root / "role-change-receipt.json", role_result)
        subprocess.run(
            ["systemctl", "start", peer_provision["unit"]],
            check=True,
            capture_output=True,
        )
        running = wait(
            "peer-running", rows, lambda v: len(v) == 5 and v[-1]["state"] == "running"
        )
        try:
            call(
                "PUT",
                "agents/" + peer["id"] + "/role",
                {
                    "operationId": "reject-active-role-" + authority,
                    "primary": "other",
                    "purpose": "Must not activate during unsettled execution.",
                    "homeRoomId": room,
                    "revision": role_result["revision"],
                },
            )
        except urllib.error.HTTPError as e:
            assert e.code == 409
            saved(root / "active-role-rejected.json", {"status": 409})
        else:
            raise AssertionError("Active responsibility mutation accepted")
        final_rows = wait(
            "pending-work-after-role",
            rows,
            lambda v: len(v) == 5 and all(r["state"] == "completed" for r in v),
        )
        role_proof = Path(peer_provision["workspace"]) / "role-continuity.txt"
        assert (
            marker in role_proof.read_text() and "maintainer" in role_proof.read_text()
        )
        assert (
            len({r["native_thread"] for r in final_rows if r["agent"] == peer["id"]})
            == 1
        )

        # An explicitly enrolled external agent can communicate as an agent.
        external_path = root / "external-credential.json"
        if not external_path.exists():
            saved(
                external_path,
                {"principalId": str(uuid4()), "token": secrets.token_urlsafe(40)},
            )
        external = json.loads(external_path.read_text())
        call(
            "POST",
            "principals",
            {
                "id": external["principalId"],
                "name": "External source peer",
                "kind": "agent",
                "enrollmentCredential": external["token"],
            },
        )
        call(
            "PUT",
            "rooms/" + workshop + "/membership",
            {
                "principalId": external["principalId"],
                "can_read": True,
                "can_post": True,
                "can_request": True,
                "revision": 0,
            },
        )
        try:
            call(
                "POST",
                "rooms/" + workshop + "/messages",
                {
                    "operationId": "unenrolled-" + authority,
                    "kind": "message",
                    "body": "Must reject before communication enrollment.",
                },
                external,
            )
        except urllib.error.HTTPError as e:
            assert e.code == 403
        else:
            raise AssertionError("Unenrolled transport accepted")
        call(
            "PUT",
            "agents/" + external["principalId"] + "/communication",
            {
                "operationId": "communication-grant-" + authority,
                "credentialDigest": digest(external["token"]),
                "allowRequests": False,
            },
        )
        before = len(rows())
        external_result = post_once(
            "external-message",
            "rooms/" + workshop + "/messages",
            {
                "operationId": "external-passive-" + authority,
                "kind": "message",
                "body": "Attributable external-agent observation; no execution requested.",
            },
            external,
        )
        assert external_result["event"]["author"] == external["principalId"]
        try:
            call(
                "POST",
                "rooms/" + workshop + "/messages",
                {
                    "operationId": "external-request-denied-" + authority,
                    "kind": "request",
                    "recipientId": glob["principalId"],
                    "body": "Must reject: communication grant is passive.",
                },
                external,
            )
        except urllib.error.HTTPError as e:
            assert e.code == 403
        else:
            raise AssertionError("Passive grant admitted execution")
        try:
            call(
                "POST",
                "rooms/" + workshop + "/messages",
                {
                    "operationId": "native-bypass-denied-" + authority,
                    "kind": "message",
                    "body": "Must reject outside native execution.",
                },
                glob,
            )
        except urllib.error.HTTPError as e:
            assert e.code == 403
        else:
            raise AssertionError("Native credential bypassed execution fence")
        time.sleep(3)
        assert len(rows()) == before

        # Cancel one new owned request; do not replay after interruption.
        cancel_receipt = post_once(
            "cancel-request",
            "rooms/" + room + "/messages",
            {
                "operationId": "cancel-proof-" + authority,
                "kind": "request",
                "recipientId": peer["id"],
                "audience": "room",
                "body": "For this disposable cancellation proof only, run sleep 20 before writing should-not-be-created.txt. "
                "Stop immediately if this request is cancelled. No other work.",
            },
        )
        pending = wait(
            "cancel-running",
            rows,
            lambda v: len(v) == 6 and v[-1]["state"] == "running",
        )
        cancelled = call("POST", "deliveries/" + pending[-1]["id"] + "/cancel", {})
        saved(root / "cancel-receipt.json", cancelled)
        end_rows = wait(
            "cancelled", rows, lambda v: len(v) == 6 and v[-1]["state"] == "cancelled"
        )
        assert not (
            Path(peer_provision["workspace"]) / "should-not-be-created.txt"
        ).exists()
        with store.pool.connection() as c:
            contexts = json_value(
                c.execute(
                    "SELECT * FROM hb_agent_context WHERE authority=%s", (authority,)
                ).fetchall()
            )
            bindings = json_value(
                c.execute(
                    "SELECT x.* FROM hb_agent_execution x JOIN hb_delivery d ON d.id=x.delivery WHERE d.authority=%s",
                    (authority,),
                ).fetchall()
            )
        assert len(contexts) == 2 and len(bindings) == 6
        turn_ids = []
        for home in [
            Path(global_receipt["home"]),
            Path(peer_provision["workspace"]).parent,
        ]:
            for f in (home / "codex-home/sessions").rglob("*.jsonl"):
                for line in f.read_text().splitlines():
                    payload = json.loads(line).get("payload", {})
                    if payload.get("type") == "task_started":
                        turn_ids.append(payload["turn_id"])
        assert len(turn_ids) == 6 and len(set(turn_ids)) == 6
        result = {
            "passed": True,
            "authorityId": authority,
            "actualNativeAgents": 2,
            "actualProviderTurns": 6,
            "persistentContexts": 2,
            "crossRoomGlobalContinuity": True,
            "crossRoomPeerContinuity": True,
            "globalCreatedRoomAgentAndProvisionedPeer": True,
            "automaticExplicitPeerCompletion": True,
            "secondHumanAfterHarnessRestart": True,
            "idleRoleChangePreservesPendingWorkAndContext": True,
            "activeRoleChangeRejected": True,
            "externalAgentAuthorship": True,
            "passiveTrafficNewTurns": 0,
            "nativeCredentialCannotBypassExecutionFence": True,
            "cancelledOriginalRequest": end_rows[-1]["id"],
            "acceptedArtifacts": [
                {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in [proof, peer_artifact, resumed, role_proof]
            ],
            "productionChanged": False,
            "physicalPhoneChanged": False,
        }
        saved(root / "result.json", result)
        print(json.dumps(result), flush=True)
    finally:
        units = stop_owned()
        for name, child in [("controller", controller), ("api", api)]:
            if child and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    errors.append(name + "-cleanup")
        saved(
            root / "cleanup.json",
            {"ownedUnits": units, "errors": errors, "productionChanged": False},
        )
        store.close()
        if errors:
            raise RuntimeError("Owned QA cleanup incomplete")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--spec", type=Path, required=True)
    args = p.parse_args()
    main(json.loads(args.spec.read_text()))
