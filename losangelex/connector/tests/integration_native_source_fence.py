"""One real native Global turn plus actual HTTP/PostgreSQL cancellation contention.

HTTP probes reuse the captured live native parent. They are protocol checks,
not additional provider tool calls or evidence of autonomous model decisions.
"""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
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

    def call(method, path, body=None, *, credential=None, provenance=None):
        req = urllib.request.Request(
            "http://127.0.0.1:18772/hollywood/v3/" + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + (credential or owner)["token"],
                "Content-Type": "application/json",
                **({"X-Hollywood-Native-Source": json.dumps(provenance)} if provenance is not None else {}),
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
            + ". Then call hollywood_ask with one blocking question (id source_fence_hold, header Qualification, question Ready for the authorized Stop exercise?, and two options Continue and Stop, each with a description). Wait for that native human response. Do not provision other agents/rooms, create business goals, start schedules or other work. The driver will deliberately cancel this admitted turn; never retry it. Keep Global's ongoing role active.",
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

        def pending_question():
            rows = current()
            with store.pool.connection() as connection:
                questions = connection.execute(
                    "SELECT id,state FROM hb_attention WHERE authority=%s AND state='pending'",
                    (setup["authorityId"],),
                ).fetchall()
            return {"deliveries": rows, "questions": questions}

        captured = wait(
            pending_question,
            lambda value: bool(value["questions"]) or any(
                d["state"] in ("completed", "failed", "unknown", "cancelled")
                for d in value["deliveries"]
            ),
        )
        ds = captured["deliveries"]
        assert len(ds) == 1 and ds[0]["state"] == "running" and len(captured["questions"]) == 1
        delivery_id = str(ds[0]["id"])
        effects = call("GET", "deliveries/" + delivery_id + "/native-effects")["effects"]
        publication = next(e for e in effects if e["source"]["tool"] == "hollywood_publish")
        assert publication["wire_body_captured"] and publication["operation"]
        source = publication["source"]
        saved(root / "captured-live-native-source.json", source)
        assert source["nativeTurn"] == ds[0]["native_turn"]
        saved(root / "native-question.json", json_value(captured["questions"][0]))

        def rejected(path, body, provenance=source, credential=glob, expected=409):
            try:
                call("POST", path, body, provenance=provenance, credential=credential)
            except HTTPError as error:
                assert error.code == expected, (error.code, expected)
                return {"path": path, "status": error.code}
            raise AssertionError("Stale/foreign source was accepted")

        route = "rooms/" + room + "/messages"
        def probe(label):
            return {
                "operationId": "source-fence:" + label + ":" + str(uuid4()),
                "kind": "message", "audience": "room",
                "body": "Owned source-fence protocol probe: " + label,
            }

        good = probe("valid")
        accepted = call("POST", route, good, provenance=source, credential=glob)
        original = call("GET", "commands/" + good["operationId"], credential=glob)
        assert accepted == original["canonicalCommand"]["acceptedResult"]
        good_effects = call("GET", "deliveries/" + delivery_id + "/native-effects")["effects"]
        own = next(e for e in good_effects if e["operation"] == good["operationId"])
        assert own["wire_body_captured"]
        assert own["wire_digest"] == original["canonicalCommand"]["wireDigest"]
        assert own["source"] == source
        assert len(good_effects) == len(effects) + 1

        cases = [rejected(route, probe("missing"), provenance=None, expected=403)]
        for key, value in [
            ("claimId", "different-claim"), ("generation", source["generation"] + 1),
            ("hostId", str(uuid4())), ("nativeThread", str(uuid4())),
            ("nativeTurn", str(uuid4())), ("requestId", str(uuid4())),
            ("contextId", "different-context"), ("nativeGoalId", str(uuid4())),
            ("roleRevision", source["roleRevision"] + 1),
        ]:
            cases.append(rejected(route, probe(key), provenance={**source, key: value}))
        cases.append(rejected(route, probe("wrong-actor"),
                              provenance={**source, "agentId": str(uuid4())}, expected=403))
        cases.append(rejected(route, probe("human-provenance"), credential=owner, expected=403))
        # The fence's provenance insertion must roll back with a later domain denial.
        denied = probe("domain-denied")
        cases.append(rejected("rooms/" + str(uuid4()) + "/messages", denied, expected=403))
        with store.pool.connection() as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM hb_native_effect WHERE operation=%s",
                (denied["operationId"],),
            ).fetchone()["n"] == 0

        # Hold the event row after the first source has acquired its separate
        # audit counter. A second writer must wait at that counter, so a replay
        # cursor cannot skip the first writer while it is still uncommitted.
        ordered = [probe("ordered-first"), probe("ordered-second")]
        before_cursor = own["sequence"]
        def blocked_query(fragment):
            with store.pool.connection() as connection:
                return connection.execute(
                    """SELECT count(*) AS n FROM pg_stat_activity
                       WHERE pid<>pg_backend_pid() AND wait_event_type='Lock'
                       AND position(%s in query)>0""", (fragment,)
                ).fetchone()["n"]
        with ThreadPoolExecutor(max_workers=2) as threads:
            with store.pool.connection() as blocker:
                blocker.execute(
                    "SELECT id FROM hb_authority WHERE id=%s FOR UPDATE",
                    (setup["authorityId"],),
                )
                first = threads.submit(call, "POST", route, ordered[0],
                                       provenance=source, credential=glob)
                wait(lambda: blocked_query("UPDATE hb_authority SET next_seq"),
                     lambda n: n >= 1, 10)
                second = threads.submit(call, "POST", route, ordered[1],
                                        provenance=source, credential=glob)
                wait(lambda: blocked_query("hb_native_effect_cursor"),
                     lambda n: n >= 1, 10)
                during = call("GET", "deliveries/" + delivery_id
                              + "/native-effects?after=" + str(before_cursor))
                assert during["effects"] == []
            first.result(timeout=20)
            second.result(timeout=20)
        after = call("GET", "deliveries/" + delivery_id
                     + "/native-effects?after=" + str(before_cursor))
        assert [e["operation"] for e in after["effects"]] == [
            p["operationId"] for p in ordered
        ]
        page = call("GET", "deliveries/" + delivery_id
                    + "/native-effects?after=" + str(before_cursor) + "&limit=1")
        assert len(page["effects"]) == 1 and page["nextCursor"] == after["effects"][0]["sequence"]
        saved(root / "actual-cursor-ordering.json", {
            "providerCalls": 0, "realPostgresRowContention": True,
            "eventRowBlockedFirstWriter": True, "auditCounterBlockedSecondWriter": True,
            "noUncommittedRowsExposed": True, "committedOrderAndPaginationVerified": True,
            "sequences": [e["sequence"] for e in after["effects"]],
        })

        other_root = root / "other-enterprise"
        initialize(json.loads(database.read_text()), other_root, "Source fence isolation")
        other = json.loads((other_root / "installation-intent.json").read_text())
        try:
            call("GET", "deliveries/" + delivery_id + "/native-effects",
                 credential=other["credentials"]["Owner"])
        except HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("Cross-enterprise provenance leaked")

        late = probe("queued-behind-stop")
        lock_key = "native-authority:" + setup["authorityId"]
        def waiters():
            with store.pool.connection() as connection:
                return connection.execute(
                    """SELECT count(*) AS n FROM pg_locks
                       WHERE locktype='advisory' AND NOT granted
                       AND classid=((hashtextextended(%s,0)>>32)&4294967295)::oid
                       AND objid=(hashtextextended(%s,0)&4294967295)::oid""",
                    (lock_key, lock_key),
                ).fetchone()["n"]

        with ThreadPoolExecutor(max_workers=2) as threads:
            with store.pool.connection() as blocker:
                blocker.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock_key,)
                )
                stop = threads.submit(call, "POST", "deliveries/" + delivery_id + "/cancel")
                wait(waiters, lambda n: n >= 1, 10)
                delayed = threads.submit(rejected, route, late)
                contention = wait(waiters, lambda n: n >= 2, 10)
                saved(root / "actual-postgres-contention.json",
                      {"matchingBlockedTransactions": contention,
                       "cancelQueuedBeforeOldSourceWriter": True})
            stopped = stop.result(timeout=20)
            late_rejection = delayed.result(timeout=20)
        assert stopped["delivery"]["cancellation_requested"]
        late_agent = str(uuid4())
        admin = {
            "operationId": "source-fence:late-admin:" + str(uuid4()),
            "id": late_agent, "name": "Never created by cancelled source",
            "kind": "agent", "enrollmentCredential": secrets.token_urlsafe(48),
        }
        late_admin = rejected("principals", admin)
        ds = wait(current, lambda rows: rows[0]["state"] in ("cancelled", "unknown"), 45)
        assert ds[0]["state"] == "cancelled"
        with store.pool.connection() as connection:
            assert not connection.execute(
                "SELECT id FROM hb_principal WHERE id=%s", (late_agent,)
            ).fetchone()
            assert not connection.execute(
                "SELECT event FROM hb_command WHERE principal=%s AND operation=%s",
                (glob["principalId"], late["operationId"]),
            ).fetchone()
        original_after = call("GET", "commands/" + good["operationId"], credential=glob)
        assert original_after == original
        saved(root / "protocol-checks.json", {
            "providerCalls": 0, "validParentAccepted": True,
            "invalidSources": cases, "domainDenialProvenanceRolledBack": True,
            "crossEnterpriseReadDenied": True,
            "actualContention": contention, "latePublication": late_rejection,
            "lateAdministration": late_admin,
            "latePrincipalAbsent": True, "lateMessageAbsent": True,
            "originalReceiptAfterCancelUnchanged": True,
        })
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

        wait(executor, lambda value: value and value["state"] == "stopped", 45)
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
            "actualGlobalQuestionAndCancellation": True,
            "nativeSourceValidatedAtMutation": True,
            "actualPostgresStopBeforeDelayedWriter": True,
            "latePublicationAndAdministrationDenied": True,
            "sourceIsNativeParentProvenanceNotToolArgumentCryptographicAttestation": True,
            "newGlobalControlAdmissionQualified": False,
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
        result["sourceEffects"] = call("GET", "deliveries/" + delivery_id + "/native-effects")["effects"]
        saved(root / "result.json", result)
        print(json.dumps(result), flush=True)
    finally:
        errors = []
        if g:
            for args in [
                ["systemctl", "stop", g["unit"]],
                ["systemctl", "disable", g["unit"]],
            ]:
                value = subprocess.run(args, capture_output=True, check=False)
                if value.returncode:
                    errors.append("owned Global unit cleanup failed")
        for name, child in [("controller", controller), ("api", api)]:
            if child and child.poll() is None:
                try:
                    child.terminate()
                    child.wait(timeout=20)
                except (OSError, subprocess.TimeoutExpired) as error:
                    errors.append(name + ":" + type(error).__name__)
        owned = (
            []
            if g is None
            else subprocess.run(
                ["ps", "-u", str(g["uid"]), "-o", "pid=,comm="],
                capture_output=True,
                text=True,
                check=False,
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
