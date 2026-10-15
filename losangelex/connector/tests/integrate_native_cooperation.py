"""Finite installed independent peers, two human principals, Kanban and real verification."""

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
from lax_connector.journal import saved
from lax_connector.host import (
    enroll as enroll_host,
    supervise as sample_host,
    resources,
)
from lax_connector.linux_admin import provision as provision_global
from lax_connector.linux_worker import provision as provision_worker


def cleanup(spec):
    root = Path(spec["evidence"])
    intent = root / "enterprise/installation-intent.json"
    if not intent.exists():
        return
    authority = json.loads(intent.read_text())["authorityId"]
    workers = Path("/var/lib/harness") / authority / "workers"
    for file in workers.glob("*/provision-receipt.json"):
        receipt = json.loads(file.read_text())
        assert receipt["authorityId"] == authority
        assert receipt["unit"].startswith(
            "lax-worker-" + authority.replace("-", "")[:8] + "-"
        )
        subprocess.run(
            ["systemctl", "stop", receipt["unit"]],
            check=True,
            timeout=35,
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "disable", receipt["unit"]],
            check=True,
            timeout=15,
            capture_output=True,
        )
    saved(
        root / "cleanup.json",
        {
            "authorityId": authority,
            "ownedWorkerUnitsStoppedAndDisabled": True,
            "productionChanged": False,
        },
    )


def qualify_attempt_journals(spec, workers, python):
    """Inspect the actual completed cohort; no unit or model is started."""
    root = Path(spec["evidence"])
    candidates = []
    for name, worker in sorted(workers.items()):
        service = subprocess.run(
            [
                "systemctl",
                "show",
                worker["unit"],
                "-p",
                "ActiveState",
                "-p",
                "UnitFileState",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "ActiveState=inactive" in service and "UnitFileState=disabled" in service
        state = Path(worker["workspace"]).parent / "state"
        records = list(state.glob("executions/*/*/execution.json"))
        if len(records) > 1:
            candidates.append((name, worker, state))
    assert len(candidates) == 1
    name, worker, state = candidates[0]
    latest = state / "execution.json"
    selected = state / "execution-current.json"
    attempts = sorted(
        (
            json.loads(path.read_text())
            for path in state.glob("executions/*/*/execution.json")
        ),
        key=lambda row: row["request"]["seq"],
    )
    assert len(attempts) == 2
    older, current = attempts
    assert json.loads(latest.read_text())["delivery"]["id"] == current["delivery"]["id"]
    canonical = (
        state
        / "executions"
        / current["delivery"]["id"]
        / str(current["delivery"]["generation"])
        / "execution.json"
    )
    protected = {path: path.read_bytes() for path in (latest, selected, canonical)}
    native_files = [
        path
        for item in workers.values()
        for path in (Path(item["workspace"]).parent / "codex-home/sessions").rglob(
            "*.jsonl"
        )
    ]

    def provider_turns():
        return sum(
            json.loads(line).get("payload", {}).get("type") == "task_started"
            for path in native_files
            for line in path.read_text().splitlines()
        )

    before_recovery = provider_turns()
    assert before_recovery == 4
    command = [
        "runuser",
        "-u",
        worker["linuxUser"],
        "--",
        python,
        "-m",
        "lax_connector.connector",
        "--config",
        str(state.parent / "connector.json"),
        "--reconcile-delivery",
        older["delivery"]["id"],
        "--generation",
        str(older["delivery"]["generation"]),
    ]
    saved(
        root / "old-attempt-recovery-intent.json",
        {
            "deliveryId": older["delivery"]["id"],
            "generation": older["delivery"]["generation"],
            "originalRequestReplayed": False,
            "expectedNewModelTurns": 0,
        },
    )
    with (root / "old-attempt-recovery.log").open("wb") as output:
        recovery = subprocess.run(
            command, stdout=output, stderr=subprocess.STDOUT, timeout=90
        )
    assert recovery.returncode == 0
    assert all(path.read_bytes() == value for path, value in protected.items())
    assert provider_turns() == before_recovery
    older_path = (
        state
        / "executions"
        / older["delivery"]["id"]
        / str(older["delivery"]["generation"])
        / "execution.json"
    )
    old_receipt = json.loads(older_path.read_text())
    assert old_receipt["reconciled"] and old_receipt["state"] == "completed"
    assert not list((state / "executions/open").iterdir())
    journal_result = {
        "passed": True,
        "actualNativePeers": 3,
        "actualProviderTurns": before_recovery,
        "agentWithMultipleAttempts": name,
        "olderAttemptReconciled": older["delivery"]["id"],
        "laterAttemptPreserved": current["delivery"]["id"],
        "latestSelectorProjectionAndCanonicalBytesUnchanged": True,
        "oldAttemptRecoveryNewModelTurns": 0,
        "oldRequestOrArtifactReplayed": False,
        "allOwnedWorkersStopped": True,
        "unknownOriginalGlobalControlJourneyQualified": False,
    }
    saved(root / "attempt-journal-recovery.json", journal_result)
    result_path = root / "result.json"
    final_result = json.loads(result_path.read_text())
    final_result["attemptJournalRecovery"] = journal_result
    saved(result_path, final_result)


def main(spec):
    os.umask(0o077)
    autonomous = spec.get("autonomousPeerRequest", False)
    memory = spec.get("decisionMemory", False)
    assert not memory or autonomous
    assert os.geteuid() == 0 and socket.gethostname() == "ozzz-aosp"
    root = Path(spec["evidence"])
    root.mkdir(mode=0o700)
    saved(
        root / "intent.json",
        {
            "scope": "Three fresh independent LAX peers, "
            + (
                "one human execution request and autonomous peer delegation"
                if autonomous
                else "two explicit human requests"
            )
            + ", one authorized material review; four intended provider turns",
            "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "productionChanged": False,
            "physicalPhoneChanged": False,
        },
    )
    runtime = Path(spec["runtime"])
    python = str(runtime / "venv/bin/python")
    port = 18775
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    initialize(
        json.loads(Path(spec["databaseConfig"]).read_text()),
        root / "enterprise",
        "Native peer cooperation",
    )
    install = json.loads((root / "enterprise/installation-intent.json").read_text())
    owner = install["credentials"]["Owner"]
    authority = install["authorityId"]
    room = install["globalRoomId"]
    host = str(uuid4())
    base = "http://127.0.0.1:" + str(port) + "/hollywood/v3/"
    saved(
        Path("/opt/hetzner-blue-team/coordination/announcements")
        / ("native-peer-cooperation-" + authority + ".json"),
        {
            "owner": "01a12c58-d21a-79b0-a512-0c3bc6dc0ee4",
            "host": "ozzz-aosp",
            "privateListener": "127.0.0.1:" + str(port),
            "scope": "Fresh finite independent peer cooperation; no stopped historical owner resumed",
            "runtime": str(runtime),
            "credentialIntent": str(root / "enterprise/installation-intent.json"),
            "rollback": "Stop API and only worker units for authority " + authority,
        },
    )
    log = (root / "api.log").open("ab")
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
    store = None
    controller = None
    controller_log = None
    trace = []
    workers = {}

    def call(method, path, payload=None, actor=None):
        actor = actor or owner
        op = {
            "actor": actor["principalId"],
            "method": method,
            "path": path,
            "body": payload,
        }
        saved(root / "last-http-intent.json", op)
        request = urllib.request.Request(
            base + path,
            method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + actor["token"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            value = json.load(response)
        trace.append({**op, "result": value})
        saved(root / "http-trace.json", trace)
        return value

    def wait_for(label, read, predicate, timeout=300):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert api.poll() is None, "Owned API stopped"
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
            label + " did not settle; inspect original evidence, do not resubmit"
        )

    try:
        for _ in range(100):
            assert api.poll() is None
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:" + str(port) + "/health", timeout=2
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Owned API failed readiness")
        global_receipt = provision_global(
            {
                "installationIntent": str(root / "enterprise/installation-intent.json"),
                "hollywoodUrl": base.removesuffix("/hollywood/v3/"),
                "hostId": host,
                "binary": spec["binary"],
                "interpreter": python,
                "approvedModelAuthFile": spec["approvedModelAuthFile"],
                "model": "gpt-6.1-sol",
                "effort": "xhigh",
            }
        )
        saved(root / "global-provision.json", global_receipt)
        import secrets

        for name, kind in [
            ("Planner", "agent"),
            ("Builder", "agent"),
            ("Verifier", "agent"),
            ("SecondHuman", "human"),
        ]:
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
                    "kind": kind,
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
            if kind == "human":
                second_human = credential
                continue
            call(
                "PUT",
                "agents/" + credential["principalId"] + "/role",
                {
                    "primary": name.lower(),
                    "purpose": "Finite peer cooperation qualification: " + name,
                    "homeRoomId": room,
                    "revision": 1,
                    "nativeGoalScope": "work",
                },
            )
            call(
                "POST",
                "placements",
                {
                    "hostId": host,
                    "name": "native-peer-host",
                    "identityFingerprint": "owned-native-peer-host-" + authority,
                    "capabilities": {"nativeLax": True},
                    "agentId": credential["principalId"],
                },
            )
            receipt = provision_worker(
                {
                    "authorityId": authority,
                    "agentId": credential["principalId"],
                    "credential": credential["token"],
                    "hollywoodUrl": base.removesuffix("/hollywood/v3/"),
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
        host_enrollment = enroll_host(
            {
                "authorityId": authority,
                "hostId": host,
                "hollywoodUrl": base.removesuffix("/hollywood/v3/"),
                "administratorCredential": owner,
                "policy": {
                    "maxConcurrent": resources()["cpuSlots"],
                    "reservedInteractive": 1,
                    "controlAgentIds": [
                        install["credentials"]["Global"]["principalId"]
                    ],
                    "memoryPerTurnBytes": 512 * 1024**2,
                    "reserveMemoryBytes": 1024**3,
                    "sampleMaxAgeSeconds": 20,
                    "connectorMaxAgeSeconds": 30,
                },
            }
        )
        saved(root / "host-enrollment.json", host_enrollment)
        sample_host(
            json.loads(Path(host_enrollment["configPath"]).read_text()), once=True
        )
        controller_log = (root / "controller.log").open("ab")
        controller = subprocess.Popen(
            [
                python,
                "-m",
                "lax_connector.host",
                "--serve",
                host_enrollment["configPath"],
            ],
            stdout=controller_log,
            stderr=subprocess.STDOUT,
        )
        saved(
            root / "controller-process.json",
            {
                "pid": controller.pid,
                "configPath": host_enrollment["configPath"],
                "modelsStarted": 0,
            },
        )
        builder = workers["Builder"]
        verifier = workers["Verifier"]
        planner = workers["Planner"]
        builder_id = builder["agentId"]
        verifier_id = verifier["agentId"]
        work = Path(builder["workspace"])
        home = work.parent
        # Explicit Unix read-only capability for this disposable, same-host artifact.
        # This is fixture provisioning, not a claimed cross-host retrieval service.
        for args in [
            ["setfacl", "-m", "u:" + verifier["linuxUser"] + ":--x", str(home)],
            [
                "setfacl",
                "-m",
                "u:"
                + verifier["linuxUser"]
                + ":r-x,d:u:"
                + verifier["linuxUser"]
                + ":r-x",
                str(work),
            ],
        ]:
            subprocess.run(args, check=True, capture_output=True)
        assert (
            subprocess.run(
                [
                    "runuser",
                    "-u",
                    verifier["linuxUser"],
                    "--",
                    "test",
                    "-r",
                    str(home / "connector.json"),
                ],
                check=False,
            ).returncode
            != 0
        )
        assert (
            subprocess.run(
                ["runuser", "-u", verifier["linuxUser"], "--", "test", "-w", str(work)],
                check=False,
            ).returncode
            != 0
        )
        marker = (
            "HOLLYWOOD_CURRENT_DECISION_V2\n"
            if memory
            else "HOLLYWOOD_PEER_COOPERATION_V1\n"
        )
        artifact = work / "cooperation.txt"
        memory_evidence = None
        if memory:
            seed = call(
                "POST",
                "rooms/" + room + "/messages",
                {
                    "operationId": "decision-source-v1",
                    "kind": "message",
                    "body": "Initial scoped artifact direction; a correction may arrive before implementation.",
                },
            )
            decision_id = str(uuid4())
            initial_decision = {
                "operationId": "decision-v1",
                "id": decision_id,
                "key": "artifact.content",
                "revision": 0,
                "goalId": None,
                "state": "active",
                "body": "Write cooperation.txt with exactly HOLLYWOOD_CURRENT_DECISION_V1 followed by one newline.",
                "sourceEventId": seed["event"]["id"],
            }
            original_decision = call(
                "POST", "rooms/" + room + "/decisions", initial_decision
            )

        objective = (
            "Create one canonical goal from this human request, reviewBudget exactly 1 (one material verifier review is authorized). "
            "Then use hollywood_cooperation_set with policy kanban_pull, reviewerId "
            + verifier_id
            + ", executorIds ["
            + builder_id
            + "], cooperationRevision 0. "
            "Create exactly one open work record (ownerId null), no dependencies, in this current room. "
            "Its specification must ask Builder to "
            + (
                "read hollywood_briefing and write cooperation.txt with exactly the current artifact.content decision's required contents"
                if memory
                else "write cooperation.txt containing exactly " + repr(marker)
            )
            + ", check it, complete the native work goal, and submit using hollywood_work_report with artifactPaths [cooperation.txt]. "
            "Its acceptance must require Verifier to independently read "
            + str(artifact)
            + " on execution host "
            + host
            + " (this fixture explicitly grants Verifier Unix read-only access), "
            "verify exact contents, sha256 and size against the canonical evidence, accept the work, then accept the goal. "
            "Do not assign or claim the open work yourself. Finish after creating this goal/contract/work; do not poll, wait, create agents or start other work. "
            "You are one independent peer. The room default is Global, but this request is explicitly addressed to you; you must own its goal."
        )
        if autonomous:
            stakeholder = call(
                "POST",
                "rooms/" + room + "/messages",
                {
                    "operationId": "stakeholder-note",
                    "kind": "message",
                    "body": "Stakeholder requirement: use independent verification and leave accepted work idle.",
                },
                second_human,
            )
            assert stakeholder["deliveries"] == []
            saved(root / "stakeholder-note.json", stakeholder)
            if memory:
                objective += (
                    " Read hollywood_briefing before planning. The work specification and acceptance must reference the CURRENT artifact.content decision, not hard-code the first version's bytes. "
                    "After creating the goal, cooperation contract and open work, BEFORE requesting Builder, "
                    "use hollywood_ask exactly once with question id proceed, header Proceed, question 'Proceed after reviewing the current artifact decision?', "
                    "and one option label Proceed, description Continue this finite mission. "
                    "Wait for the attributable answer, then read hollywood_briefing again and use the corrected current decision. "
                    "Tell Builder and Verifier to read their current briefings and independently validate against that decision. "
                )
            objective += (
                " After creating the open work, use hollywood_request to send exactly one bounded request directly to Builder "
                + builder_id
                + " in this same room (explicit recipientId). Include the created goal/work IDs and tell Builder "
                "to claim exactly that work at revision 1 with hollywood_work_claim, then end its coordination turn "
                "so the separate native assignment can execute. Do not wait or poll. This peer delegation is authorized "
                "by this one human request; no second human execution request will be sent."
            )
        request = call(
            "POST",
            "rooms/" + room + "/messages",
            {
                "operationId": "native-peer-plan",
                "kind": "request",
                "body": objective,
                "recipientId": planner["agentId"],
            },
        )
        saved(root / "plan-request.json", request)
        plan_delivery = request["deliveries"][0]["id"]
        if memory:
            attention_page = wait_for(
                "original-native-question",
                lambda: call("GET", "rooms/" + room + "/attention?after=0&limit=100"),
                lambda page: any(
                    q["attention"]["state"] == "pending"
                    and q["attention"]["agent"] == planner["agentId"]
                    for q in page["attention"]
                ),
                240,
            )
            pending = [
                q
                for q in attention_page["attention"]
                if q["attention"]["state"] == "pending"
                and q["attention"]["agent"] == planner["agentId"]
            ]
            assert len(pending) == 1
            attention = pending[0]
            corrected_source = call(
                "POST",
                "rooms/" + room + "/messages",
                {
                    "operationId": "decision-source-v2",
                    "kind": "message",
                    "body": "Correct artifact.content to V2 before implementing. The original native question remains the same.",
                },
            )
            corrected_decision = call(
                "POST",
                "rooms/" + room + "/decisions",
                {
                    **initial_decision,
                    "operationId": "decision-v2",
                    "revision": 1,
                    "body": "Write cooperation.txt with exactly HOLLYWOOD_CURRENT_DECISION_V2 followed by one newline.",
                    "sourceEventId": corrected_source["event"]["id"],
                },
            )
            api.terminate()
            api.wait(timeout=20)
            api = subprocess.Popen(api.args, stdout=log, stderr=subprocess.STDOUT)
            wait_for(
                "api-restart", lambda: call("GET", "rooms"), lambda page: bool(page), 30
            )
            original = call("GET", "attention/" + attention["attention"]["id"])
            assert original["scope"] == attention["scope"]
            answered = call(
                "POST",
                "attention/" + attention["attention"]["id"] + "/response",
                {
                    "operationId": "original-proceed-answer",
                    "scope": original["scope"],
                    "response": {"answers": {"proceed": {"answers": ["Proceed"]}}},
                },
            )
            memory_evidence = {
                "originalDecision": original_decision,
                "correctedDecision": corrected_decision,
                "originalAttentionId": attention["attention"]["id"],
                "sameAttentionAcrossAPIRestart": True,
                "answerReceipt": answered,
                "modelExecutionRequests": 1,
                "questionAnswerIsNotReplacementExecution": True,
            }
            saved(root / "decision-memory.json", memory_evidence)
        wait_for(
            "planner-completion",
            lambda: call("GET", "deliveries/" + plan_delivery),
            lambda r: r["delivery"]["state"] in ["completed", "failed", "unknown"],
            240,
        )
        store = Store(json.loads(Path(spec["databaseConfig"]).read_text()))
        with store.pool.connection() as c:
            goal = c.execute(
                "SELECT * FROM hb_goal WHERE authority=%s", (authority,)
            ).fetchall()
            assert len(goal) == 1 and str(goal[0]["owner"]) == planner["agentId"]
            rows = c.execute(
                "SELECT * FROM hb_work WHERE authority=%s", (authority,)
            ).fetchall()
            assert len(rows) == 1
            if autonomous:
                assert rows[0]["owner"] is None or str(rows[0]["owner"]) == builder_id
            else:
                assert rows[0]["owner"] is None and rows[0]["delivery"] is None
            gid, wid = str(goal[0]["id"]), str(rows[0]["id"])
        if not autonomous:
            claim_request = call(
                "POST",
                "rooms/" + room + "/messages",
                {
                    "operationId": "native-peer-claim",
                    "kind": "request",
                    "body": "For existing authorized goal "
                    + gid
                    + ", claim exactly open work "
                    + wid
                    + " at revision 1 using hollywood_work_claim, then end this coordination request. The claim queues its separate native assignment. Do not implement or report it in this turn, and do not create a replacement goal or work item.",
                    "recipientId": builder_id,
                },
                second_human,
            )
            saved(root / "claim-request.json", claim_request)

        def results():
            with store.pool.connection() as c:
                g = c.execute("SELECT * FROM hb_goal WHERE id=%s", (gid,)).fetchone()
                w = c.execute("SELECT * FROM hb_work WHERE id=%s", (wid,)).fetchone()
                deliveries = c.execute(
                    "SELECT id,agent,state,native_thread,native_turn FROM hb_delivery WHERE authority=%s ORDER BY id",
                    (authority,),
                ).fetchall()
                return json.loads(
                    json.dumps(
                        {"goal": g, "work": w, "deliveries": deliveries}, default=str
                    )
                )

        result = wait_for(
            "accepted-real-artifact",
            results,
            lambda r: (
                r["goal"]["state"] == "accepted"
                and all(d["state"] == "completed" for d in r["deliveries"])
            ),
            420,
        )
        assert len(result["deliveries"]) == 4
        if autonomous:
            with store.pool.connection() as c:
                peer_requests = c.execute(
                    "SELECT e.id FROM hb_event e JOIN hb_delivery d ON d.event=e.id "
                    "WHERE e.authority=%s AND e.author=%s AND e.recipient=%s AND e.kind='request' AND e.source=%s",
                    (authority, planner["agentId"], builder_id, request["event"]["id"]),
                ).fetchall()
                assert len(peer_requests) == 1
        assert result["work"]["state"] == "accepted" and artifact.read_text() == marker
        actual = {
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "size": artifact.stat().st_size,
        }
        evidence = result["work"]["evidence"]
        assert len(evidence) == 1
        assert (
            evidence[0]["sha256"] == actual["sha256"]
            and evidence[0]["size"] == actual["size"]
            and evidence[0]["hostId"] == host
        )
        assert (
            subprocess.run(
                [
                    "runuser",
                    "-u",
                    verifier["linuxUser"],
                    "--",
                    "test",
                    "-w",
                    str(artifact),
                ],
                check=False,
            ).returncode
            != 0
        )
        before = {d["id"]: d["native_turn"] for d in result["deliveries"]}
        call(
            "POST",
            "rooms/" + room + "/messages",
            {
                "operationId": "native-passive-completion",
                "kind": "message",
                "body": "Finite qualification accepted; no remaining work. Observers remain silent.",
            },
        )
        time.sleep(8)
        quiet = results()
        assert {d["id"]: d["native_turn"] for d in quiet["deliveries"]} == before
        # Inspect captured connector receipts, not a replacement native turn.
        contexts = []
        for name, w in workers.items():
            state = Path(w["workspace"]).parent / "state"
            for record in state.glob("context-*.json"):
                item = json.loads(record.read_text())
                deliveries = [
                    d
                    for d in result["deliveries"]
                    if d["native_thread"] == item["nativeThread"]
                ]
                assert len(deliveries) == 1
                contexts.append(
                    {
                        "agent": name,
                        "contextRecord": str(record),
                        "contextId": item["contextId"],
                        "state": deliveries[0]["state"],
                        "nativeThread": item["nativeThread"],
                        "nativeTurn": deliveries[0]["native_turn"],
                    }
                )
        assert len(contexts) == len(result["deliveries"])
        saved(
            root / "result.json",
            {
                "passed": True,
                "authorityId": authority,
                "roomId": room,
                "goalId": gid,
                "workId": wid,
                "artifact": {**actual, "hostId": host, "path": str(artifact)},
                "deliveries": result["deliveries"],
                "contexts": contexts,
                "roomDefaultAgent": install["credentials"]["Global"]["principalId"],
                "goalOwner": planner["agentId"],
                "explicitHumanRequests": 1 if autonomous else 2,
                "autonomousPeerRequest": autonomous,
                "decisionMemory": memory_evidence,
                "humanContributions": 2,
                "distinctHumanPrincipals": [
                    owner["principalId"],
                    second_human["principalId"],
                ],
                "nativePeers": 3,
                "nativeDeliveries": 4,
                "independentVerifier": verifier_id,
                "passivePublicationCreatedNoDelivery": True,
                "productionChanged": False,
                "physicalPhoneChanged": False,
                "crossHostQualified": False,
                "artifactAccess": "Explicit same-host disposable Unix ACL; full artifact capability service remains required",
            },
        )
        if spec.get("attemptJournalRecovery"):
            cleanup(spec)
            qualify_attempt_journals(spec, workers, python)
        print(
            json.dumps(
                {
                    "passed": True,
                    "nativePeers": 3,
                    "deliveries": 4,
                    "productionChanged": False,
                }
            )
        )
    finally:
        if store:
            store.close()
        cleanup(spec)
        if controller is not None and controller.poll() is None:
            controller.terminate()
            controller.wait(timeout=15)
        if controller_log:
            controller_log.close()
        if api.poll() is None:
            api.terminate()
            api.wait(timeout=20)
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    if args.cleanup:
        cleanup(spec)
    else:

        def stop(signum, frame):
            raise InterruptedError("Owned qualification stopped")

        signal.signal(signal.SIGTERM, stop)
        main(spec)
