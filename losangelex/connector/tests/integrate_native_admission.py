"""Finite real native load/control/portfolio qualification on one enrolled Linux host."""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.store import Store
from lax_connector.host import enroll, supervise
from lax_connector.journal import saved
from lax_connector.linux_admin import provision as provision_global
from lax_connector.linux_worker import provision as provision_worker


def main(spec):
    os.umask(0o077)
    assert os.geteuid() == 0 and socket.gethostname() == "ozzz-aosp"
    root = Path(spec["evidence"])
    root.mkdir(mode=0o700)
    saved(
        root / "intent.json",
        {
            "scope": "Fresh native host admission and bounded Global portfolio",
            "expectedNativeTurns": 6,
            "productionChanged": False,
            "physicalPhoneChanged": False,
            "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
    )
    runtime = Path(spec["runtime"])
    python = str(runtime / "venv/bin/python")
    initialize(
        json.loads(Path(spec["databaseConfig"]).read_text()),
        root / "enterprise",
        "Native host admission and Global supervision",
    )
    install = json.loads((root / "enterprise/installation-intent.json").read_text())
    owner = install["credentials"]["Owner"]
    global_id = install["credentials"]["Global"]["principalId"]
    authority, room, host = (
        install["authorityId"],
        install["globalRoomId"],
        str(uuid4()),
    )
    port = 18775
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
    url = "http://127.0.0.1:" + str(port)
    saved(
        Path("/opt/hetzner-blue-team/coordination/announcements")
        / ("native-host-admission-" + authority + ".json"),
        {
            "owner": "01a12c58-d21a-79b0-a512-0c3bc6dc0ee4",
            "host": "ozzz-aosp",
            "privateListener": "127.0.0.1:" + str(port),
            "scope": "Finite fresh native load/control/portfolio qualification",
            "credentialIntent": str(root / "enterprise/installation-intent.json"),
            "rollback": "Stop only this authority's new workers, Global and controller; retain receipts",
        },
    )
    api_log = (root / "api.log").open("ab")
    api_args = [
        python,
        "-m",
        "hollywood_backbone.server",
        "--database-config",
        spec["databaseConfig"],
        "--port",
        str(port),
    ]
    api = subprocess.Popen(api_args, stdout=api_log, stderr=subprocess.STDOUT)
    controller = None
    controller_log = None
    workers = {}
    global_unit = "lax-qual-global-" + authority[:12]
    global_launched = False
    trace = []

    def call(method, route, payload=None, actor=None, expected=200):
        actor = actor or owner
        saved(
            root / "last-http-intent.json",
            {
                "method": method,
                "route": route,
                "actorId": actor["principalId"],
                "payload": payload,
            },
        )
        req = urllib.request.Request(
            url + "/hollywood/v3/" + route,
            method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + actor["token"],
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                status, value = r.status, json.load(r)
        except urllib.error.HTTPError as error:
            status, value = error.code, json.load(error)
        trace.append(
            {
                "method": method,
                "route": route,
                "actorId": actor["principalId"],
                "status": status,
                "value": value,
            }
        )
        saved(root / "http-trace.json", trace)
        assert status == expected, (route, status, value, expected)
        return value

    def wait(label, read, predicate, timeout=300):
        deadline = time.monotonic() + timeout
        value = None
        while time.monotonic() < deadline:
            assert api.poll() is None, "Original API handle stopped"
            if controller is not None:
                assert controller.poll() is None, (
                    "Original host-controller handle stopped"
                )
            try:
                value = read()
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError:
                time.sleep(0.2)
                continue
            if predicate(value):
                return value
            time.sleep(2)
        saved(root / ("timeout-" + label + ".json"), value)
        raise TimeoutError(
            label + "; inspect original receipts; do not submit a replacement"
        )

    def terminal(identity):
        return call("GET", "deliveries/" + identity)

    def request(agent, operation, body):
        return call(
            "POST",
            "rooms/" + room + "/messages",
            {
                "operationId": operation,
                "kind": "request",
                "recipientId": agent,
                "body": body,
            },
        )

    def question(agent):
        page = call("GET", "rooms/" + room + "/attention?after=0&limit=100")
        return next(
            (
                q
                for q in page["attention"]
                if q["attention"]["agent"] == agent
                and q["attention"]["state"] == "pending"
            ),
            None,
        )

    try:
        wait("api-ready", lambda: call("GET", "rooms"), lambda x: bool(x), 30)
        global_receipt = provision_global(
            {
                "installationIntent": str(root / "enterprise/installation-intent.json"),
                "hollywoodUrl": url,
                "hostId": host,
                "binary": spec["binary"],
                "interpreter": python,
                "approvedModelAuthFile": spec["approvedModelAuthFile"],
                "model": "gpt-6.1-sol",
                "effort": "xhigh",
            }
        )
        saved(root / "global-provision.json", global_receipt)
        fingerprint = "native-host-admission-" + authority
        call(
            "POST",
            "placements",
            {
                "hostId": host,
                "name": "actual-ozzz-admission-host",
                "identityFingerprint": fingerprint,
                "capabilities": {"nativeLax": True},
                "agentId": global_id,
            },
        )
        enrollment = enroll(
            {
                "authorityId": authority,
                "hostId": host,
                "hollywoodUrl": url,
                "administratorCredential": owner,
                "policy": {
                    "maxConcurrent": 3,
                    "reservedInteractive": 1,
                    "controlAgentIds": [global_id],
                    "memoryPerTurnBytes": 512 * 1024**2,
                    "reserveMemoryBytes": 1024**3,
                    "sampleMaxAgeSeconds": 20,
                    "connectorMaxAgeSeconds": 30,
                },
            }
        )
        saved(root / "host-enrollment.json", enrollment)
        config = json.loads(Path(enrollment["configPath"]).read_text())
        sample = supervise(config, once=True)
        saved(root / "initial-real-resource-sample.json", sample)
        controller_log = (root / "controller.log").open("ab")
        controller = subprocess.Popen(
            [python, "-m", "lax_connector.host", "--serve", enrollment["configPath"]],
            stdout=controller_log,
            stderr=subprocess.STDOUT,
        )
        saved(
            root / "controller-process.json",
            {
                "pid": controller.pid,
                "config": enrollment["configPath"],
                "modelsStarted": 0,
            },
        )
        call(
            "PUT",
            "agents/" + global_id + "/supervision",
            {
                "operationId": "new-portfolio-policy",
                "revision": 0,
                "roomId": room,
                "enabled": True,
                "reviewsPerWindow": 2,
                "windowSeconds": 3600,
            },
        )
        import secrets

        for name in ["HoldA", "HoldB", "Builder"]:
            credential = {
                "principalId": str(uuid4()),
                "token": secrets.token_urlsafe(40),
            }
            saved(root / (name + "-credential.json"), credential)
            call(
                "POST",
                "principals",
                {
                    "id": credential["principalId"],
                    "name": name,
                    "kind": "agent",
                    "enrollmentCredential": credential["token"],
                },
            )
            call(
                "PUT",
                "rooms/" + room + "/membership",
                {
                    "principalId": credential["principalId"],
                    "can_read": True,
                    "can_post": True,
                    "can_request": True,
                    "revision": 0,
                },
            )
            call(
                "POST",
                "placements",
                {
                    "hostId": host,
                    "name": "actual-ozzz-admission-host",
                    "identityFingerprint": fingerprint,
                    "capabilities": {"nativeLax": True},
                    "agentId": credential["principalId"],
                },
            )
            receipt = provision_worker(
                {
                    "authorityId": authority,
                    "agentId": credential["principalId"],
                    "credential": credential["token"],
                    "hollywoodUrl": url,
                    "hostId": host,
                    "binary": spec["binary"],
                    "interpreter": python,
                    "approvedModelAuthFile": spec["approvedModelAuthFile"],
                    "model": "gpt-6.1-sol",
                    "effort": "xhigh",
                }
            )
            workers[name] = receipt
            saved(root / (name + "-provision.json"), receipt)
        # Run Global with its actual administrator identity; no old owner is resumed.
        gc = json.loads(Path(global_receipt["connectorConfig"]).read_text())
        saved(
            root / "global-unit.json",
            {
                "unit": global_unit,
                "linuxUser": global_receipt["linuxUser"],
                "config": global_receipt["connectorConfig"],
            },
        )
        subprocess.run(
            [
                "systemd-run",
                "--unit=" + global_unit,
                "--property=User=" + global_receipt["linuxUser"],
                "--property=WorkingDirectory=" + gc["workspace"],
                "--property=UMask=0077",
                "--property=KillMode=control-group",
                python,
                "-m",
                "lax_connector.connector",
                "--config",
                global_receipt["connectorConfig"],
                "--serve",
            ],
            check=True,
            capture_output=True,
        )
        global_launched = True

        held = {}
        for name in ["HoldA", "HoldB"]:
            r = request(
                workers[name]["agentId"],
                "hold-" + name,
                "This is one disposable native admission test, not product work. "
                "Call hollywood_ask once with question id proceed, header Capacity, "
                "question 'Release this bounded admission hold?', one option label Release "
                "and description End this test turn. Wait for the exact human answer. "
                "Then finish without writing files or creating any goals, requests or other work.",
            )
            held[name] = r["deliveries"][0]["id"]
            q = wait(
                "question-" + name,
                lambda n=name: question(workers[n]["agentId"]),
                lambda x: x is not None,
                240,
            )
            saved(root / (name + "-attention.json"), q)
        # Both worker reservations are real native turns waiting on captured questions.
        builder = workers["Builder"]
        artifact = Path(builder["workspace"]) / "admission.txt"
        marker = "HOST_ADMISSION_VERIFIED\n"
        initial = request(
            global_id,
            "global-mission",
            "One finite mission is authorized. Create one canonical goal from this request "
            "with reviewBudget exactly 1, then create and assign exactly one work item to agent "
            + builder["agentId"]
            + " in this current room. Its specification: read hollywood_briefing, "
            "write admission.txt containing exactly "
            + repr(marker)
            + ", verify it, complete the native work goal, submit with hollywood_work_report "
            "and artifactPaths [admission.txt]. Its acceptance requires independent Global "
            "verification by reading actual bytes at "
            + str(artifact)
            + " on this same explicitly enrolled host "
            + host
            + " using your verified sudo capability if necessary, checking SHA/size against "
            "canonical evidence, then accepting work and goal. This goal authorizes one portfolio "
            "verification when evidence is ready. Preserve your ongoing native role goal. "
            "Do not implement the worker artifact yourself, do not poll or wait, "
            "do not create agents or self-request. End after assignment; Global's standing "
            "portfolio policy will deliver the material result later.",
        )
        initial_id = initial["deliveries"][0]["id"]
        admitted = wait(
            "reserved-global-admission",
            lambda: terminal(initial_id),
            lambda x: (
                x["delivery"]["state"]
                in ("claimed", "running", "completed", "failed", "unknown")
            ),
            30,
        )
        assert admitted["delivery"]["state"] in ("claimed", "running", "completed"), (
            admitted
        )
        trace_row = admitted["admissionTrace"]
        assert trace_row["queue_class"] == "interactive"
        wait(
            "global-mission-completed",
            lambda: terminal(initial_id),
            lambda x: x["delivery"]["state"] in ("completed", "failed", "unknown"),
            300,
        )
        store = Store(json.loads(Path(spec["databaseConfig"]).read_text()))
        with store.pool.connection() as c:
            goals = c.execute(
                "SELECT * FROM hb_goal WHERE authority=%s", (authority,)
            ).fetchall()
            work = c.execute(
                "SELECT * FROM hb_work WHERE authority=%s", (authority,)
            ).fetchall()
            assert len(goals) == len(work) == 1
            gid, wid, worker_delivery = (
                str(goals[0]["id"]),
                str(work[0]["id"]),
                str(work[0]["delivery"]),
            )
        store.close()
        queued = wait(
            "visible-worker-blocker",
            lambda: call("GET", "work/" + wid),
            lambda x: (
                x["admission"]
                and x["admission"]["blocker"] == "worker_capacity_reserved_for_control"
            ),
            30,
        )
        assert queued["execution"]["state"] == "pending" and not artifact.exists()
        control = request(
            global_id,
            "global-control-under-load",
            "Report the current original admission state for work "
            + wid
            + " using hollywood_work_read. Explain its queue reason concisely through Hollywood. "
            "This is an immediate control/status request only; do not change tasks, answer "
            "other people's questions, cancel work, self-request, poll, or wait.",
        )
        control_id = control["deliveries"][0]["id"]
        wait(
            "control-completed-under-load",
            lambda: terminal(control_id),
            lambda x: x["delivery"]["state"] in ("completed", "failed", "unknown"),
            240,
        )
        assert terminal(control_id)["delivery"]["state"] == "completed"
        assert terminal(worker_delivery)["delivery"]["state"] == "pending"
        for name, identity in held.items():
            assert terminal(identity)["delivery"]["state"] == "running"
        saved(
            root / "loaded-control-evidence.json",
            {
                "heldNativeDeliveries": held,
                "queuedWorker": worker_delivery,
                "queuedReason": queued["admission"],
                "globalInitial": terminal(initial_id),
                "globalControl": terminal(control_id),
                "artifactNotYetExecuted": True,
            },
        )
        # Cancellation is an independent API control, not another model request.
        cancellation = call("POST", "deliveries/" + held["HoldA"] + "/cancel", {})
        stopped = wait(
            "hold-a-stopped",
            lambda: terminal(held["HoldA"]),
            lambda x: x["delivery"]["state"] in ("cancelled", "failed", "unknown"),
            90,
        )
        assert stopped["delivery"]["state"] == "cancelled", stopped
        wait(
            "queued-builder-started",
            lambda: terminal(worker_delivery),
            lambda x: (
                x["delivery"]["state"]
                in ("claimed", "running", "completed", "failed", "unknown")
            ),
            60,
        )
        # The untouched original HoldB question remains attributable and resumable.
        attention = question(workers["HoldB"]["agentId"])
        assert attention is not None
        answer = call(
            "POST",
            "attention/" + attention["attention"]["id"] + "/response",
            {
                "operationId": "release-original-hold-b",
                "scope": attention["scope"],
                "response": {"answers": {"proceed": {"answers": ["Release"]}}},
            },
        )
        saved(
            root / "cancellation-and-answer.json",
            {"cancel": cancellation, "stop": stopped, "originalAnswer": answer},
        )
        wait(
            "hold-b-completed",
            lambda: terminal(held["HoldB"]),
            lambda x: x["delivery"]["state"] in ("completed", "failed", "unknown"),
            180,
        )

        def final():
            return call("GET", "goals/" + gid)

        accepted = wait(
            "portfolio-independent-acceptance",
            final,
            lambda x: x["goal"]["state"] == "accepted",
            420,
        )
        assert artifact.read_text() == marker
        store = Store(json.loads(Path(spec["databaseConfig"]).read_text()))
        with store.pool.connection() as c:
            rows = c.execute(
                """SELECT d.*,e.data,e.audience,e.recipient FROM hb_delivery d
                   JOIN hb_event e ON e.id=d.event WHERE d.authority=%s ORDER BY e.seq""",
                (authority,),
            ).fetchall()
        store.close()
        reviews = [r for r in rows if r["data"].get("portfolioReview")]
        assert len(reviews) == 1 and reviews[0]["audience"] == "direct"
        assert str(reviews[0]["recipient"]) == global_id
        wait(
            "original-portfolio-turn-completed",
            lambda: terminal(str(reviews[0]["id"])),
            lambda x: x["delivery"]["state"] in ("completed", "failed", "unknown"),
            120,
        )
        assert terminal(str(reviews[0]["id"]))["delivery"]["state"] == "completed"
        before = {str(r["id"]): r["native_turn"] for r in rows}
        call(
            "POST",
            "rooms/" + room + "/messages",
            {
                "operationId": "passive-no-wake",
                "kind": "message",
                "body": "Accepted finite qualification. No new work.",
            },
        )
        time.sleep(8)
        store = Store(json.loads(Path(spec["databaseConfig"]).read_text()))
        with store.pool.connection() as c:
            after = c.execute(
                "SELECT id,native_turn,state FROM hb_delivery WHERE authority=%s",
                (authority,),
            ).fetchall()
        store.close()
        assert {str(r["id"]): r["native_turn"] for r in after} == before
        assert len(after) == 6 and all(
            r["state"] in ("completed", "cancelled") for r in after
        )
        saved(
            root / "result.json",
            {
                "passed": True,
                "authorityId": authority,
                "hostId": host,
                "roomId": room,
                "goalId": gid,
                "workId": wid,
                "nativeAgents": 4,
                "nativeTurns": 6,
                "heldNativeDeliveries": held,
                "globalControlDelivery": control_id,
                "portfolioDelivery": str(reviews[0]["id"]),
                "portfolioReviews": 1,
                "actualResourceController": enrollment,
                "artifact": {
                    "path": str(artifact),
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "size": artifact.stat().st_size,
                },
                "cancellationObserved": True,
                "originalQuestionResumed": True,
                "passiveMessageCreatedNoDelivery": True,
                "qualificationPolicy": "Three slots deliberately exercise two occupied workers plus one reserved control slot; not a production ceiling",
                "productionChanged": False,
                "physicalPhoneChanged": False,
                "crossHostQualified": False,
            },
        )
        print(json.dumps({"passed": True, "nativeTurns": 6, "portfolioReviews": 1}))
    finally:
        for worker in workers.values():
            subprocess.run(
                ["systemctl", "stop", worker["unit"]],
                check=True,
                timeout=40,
                capture_output=True,
            )
            subprocess.run(
                ["systemctl", "disable", worker["unit"]],
                check=True,
                timeout=15,
                capture_output=True,
            )
        if global_launched:
            subprocess.run(
                ["systemctl", "stop", global_unit],
                check=True,
                timeout=40,
                capture_output=True,
            )
        if controller is not None and controller.poll() is None:
            controller.terminate()
            controller.wait(timeout=15)
        if api.poll() is None:
            api.terminate()
            api.wait(timeout=20)
        if controller_log:
            controller_log.close()
        api_log.close()
        saved(
            root / "cleanup.json",
            {
                "authorityId": authority,
                "onlyFreshQualificationUnitsStopped": True,
                "productionChanged": False,
            },
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()

    def stop(signum, frame):
        raise InterruptedError("Owned native qualification stopped")

    signal.signal(signal.SIGTERM, stop)
    main(json.loads(args.spec.read_text()))
