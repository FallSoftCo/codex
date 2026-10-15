"""Finite installed Global/worker cancellation integration. Never replay a saved request."""

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
from lax_connector.connector import saved
from lax_connector.linux_admin import provision


def main(spec):
    os.umask(0o077)
    root = Path(spec["evidence"])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (root / "scenario-intent.json").exists():
        raise RuntimeError(
            "Original scenario exists. Inspect its receipts and processes; never resubmit it."
        )
    if os.geteuid() != 0 or socket.gethostname() != "ozzz-aosp":
        raise RuntimeError(
            "This installed integration is restricted to its authorized OZZZ Linux qualification host"
        )
    runtime = Path(spec["runtime"])
    python = str(runtime / "venv/bin/python")
    port = spec["port"]
    with socket.socket() as check:
        check.bind(("127.0.0.1", port))
    saved(
        root / "scenario-intent.json",
        {
            "scope": "one fresh enterprise, one Global, one worker, two explicit human turns",
            "runtime": str(runtime),
            "productionChanged": False,
            "originalRequestResubmitted": False,
        },
    )
    initialize(
        json.loads(Path(spec["databaseConfig"]).read_text()),
        root / "enterprise",
        "Native lifecycle qualification",
    )
    install = json.loads((root / "enterprise/installation-intent.json").read_text())
    authority = install["authorityId"]
    owner = install["credentials"]["Owner"]
    global_id = install["credentials"]["Global"]["principalId"]
    room = install["globalRoomId"]
    host = str(uuid4())
    base = "http://127.0.0.1:" + str(port) + "/hollywood/v3/"
    trace = []
    api = None
    global_unit = "lax-lifecycle-global-" + authority.replace("-", "")[:12]
    announcement = Path("/opt/hetzner-blue-team/coordination/announcements") / (
        "harness-lifecycle-" + authority + ".json"
    )
    saved(
        announcement,
        {
            "owner": spec.get("ownerThread", "native-lifecycle-qualification"),
            "host": "ozzz-aosp",
            "privateListener": "127.0.0.1:" + str(port),
            "scope": "Fresh finite native cancellation enterprise; no old owner resumes",
            "runtime": str(runtime),
            "credentialIntent": str(root / "enterprise/installation-intent.json"),
            "rollback": "Stop "
            + global_unit
            + " and worker units only under /var/lib/harness/"
            + authority,
            "productionChanged": False,
        },
    )

    def call(method, path, payload=None, expected=200):
        request = urllib.request.Request(
            base + path,
            method=method,
            headers={
                "Authorization": "Bearer " + owner["token"],
                "Content-Type": "application/json",
            },
            data=None if payload is None else json.dumps(payload).encode(),
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status, value = response.status, json.load(response)
        except urllib.error.HTTPError as response:
            status, value = response.code, json.load(response)
        trace.append({"method": method, "path": path, "status": status, "value": value})
        saved(root / "protected-http-trace.json", trace)
        if status != expected:
            raise RuntimeError(
                "Unexpected HTTP status for " + method + " " + path + ": " + str(status)
            )
        return value

    def message(name, payload):
        saved(root / (name + "-intent.json"), payload)
        try:
            value = call("POST", "rooms/" + room + "/messages", payload)
        except Exception:
            # Observe the same original command, never repeat the POST.
            value = call("GET", "commands/" + payload["operationId"])
        saved(root / (name + "-receipt.json"), value)
        return value

    def units():
        result = []
        for receipt in (Path("/var/lib/harness") / authority / "workers").glob(
            "*/provision-receipt.json"
        ):
            value = json.loads(receipt.read_text())
            result.append(value)
        return result

    def live(pid, start=None):
        try:
            stat = Path("/proc") / str(pid) / "stat"
            fields = stat.read_text().split()
            return fields[2] != "Z" and (start is None or fields[21] == start)
        except FileNotFoundError:
            return False

    helper = None
    try:
        api_log = (root / "api.log").open("ab")
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
                str(port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=api_log,
            stderr=subprocess.STDOUT,
        )
        saved(root / "api-process.json", {"pid": api.pid, "port": port})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if api.poll() is not None:
                raise RuntimeError("Owned API exited before qualification")
            try:
                with urllib.request.urlopen(
                    base.rsplit("/hollywood/v3/", 1)[0] + "/health", timeout=2
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Owned API did not become healthy")
        global_spec = {
            "installationIntent": str(root / "enterprise/installation-intent.json"),
            "approvedModelAuthFile": spec["approvedModelAuthFile"],
            "binary": str(runtime / "native/bin/codex"),
            "interpreter": python,
            "hollywoodUrl": base.rsplit("/hollywood/v3/", 1)[0],
            "hostId": host,
            "model": "gpt-6.1-sol",
            "effort": "xhigh",
        }
        saved(root / "global-spec.json", global_spec)
        global_receipt = provision(global_spec)
        saved(root / "global-provision-receipt.json", global_receipt)
        call(
            "POST",
            "placements",
            {
                "hostId": host,
                "name": "Native lifecycle qualification OZZZ",
                "identityFingerprint": hashlib.sha256(
                    Path("/etc/machine-id").read_bytes()
                ).hexdigest(),
                "capabilities": {"localProvisioning": True},
                "agentId": global_id,
            },
        )
        saved(
            root / "global-service-intent.json",
            {"unit": global_unit, "linuxUser": global_receipt["linuxUser"]},
        )
        subprocess.run(
            [
                "systemd-run",
                "--unit=" + global_unit,
                "--uid=" + global_receipt["linuxUser"],
                "--property=UMask=0077",
                "--property=MemoryMax=3G",
                "--property=CPUQuota=200%",
                "--property=RuntimeMaxSec=700",
                "--property=WorkingDirectory=" + global_receipt["home"] + "/work",
                python,
                "-m",
                "lax_connector.connector",
                "--config",
                global_receipt["connectorConfig"],
                "--serve",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        helper_code = "import os,json,time;from pathlib import Path;Path('cancel-started.json').write_text(json.dumps({'pid':os.getpid()}));time.sleep(180);Path('cancel-finished.txt').write_text('SHOULD_NOT_RUN\\n')"
        command = "python3 -c " + __import__("shlex").quote(helper_code)
        work_instruction = (
            "Finite native cancellation exercise. Use exec_command with yield_time_ms=1000 to run exactly: "
            + command
            + ". Keep the returned native process/session owned by this execution; do not detach with &, nohup, sudo or another service. "
            "Then immediately call hollywood_ask with one question id continue, header Continue, text 'Continue the disposable lifecycle helper?'. "
            "Wait for the exact human response; do not poll the helper or start another turn. Cancellation may arrive while you wait. "
            "If answered continue, use write_stdin once on the original session with yield_time_ms=240000, then verify its artifact and complete/report the work. "
            "Do not create workers, schedules or other effects."
        )
        initial = {
            "operationId": "lifecycle-native-initial",
            "kind": "request",
            "audience": "room",
            "recipientId": global_id,
            "body": "Run one finite native lifecycle qualification. Create a fresh worker named Lifecycle engineer, its Engineering room, explicit read/post grants and home role; provision its separate non-sudo Linux execution using the provided tools. "
            "Create one goal titled Native cancellation qualification, objective Prove scoped cancellation of a native worker helper and pending human question, acceptance Both native execution and work acknowledge cancellation, the helper stops without its finish effect, and stale human answers cannot execute. Set reviewBudget=0. "
            "Add and assign exactly one work item with the following instructions and matching cancellation acceptance criteria. After delegation, end your turn promptly with goal/work IDs. Keep your native coordination goal active. Do not poll, wait, schedule, auto-review or mark completion. Worker instructions:\n"
            + work_instruction,
        }
        if spec.get("exerciseStaleGrant"):
            initial["body"] += (
                " Administrative recovery qualification: after creating the room, intentionally attempt one grant with revision=0 to remove the owner's can_request right (keep read/post). Expect a known 409, not unknown delivery. Then inspect hollywood_room_info, use the actual current membership revision, and continue provisioning with can_request=false. Do not repeat an uncertain effect."
            )
        accepted = message("initial", initial)
        initial_delivery = accepted["deliveries"][0]["id"]
        goal = work = attention = worker_receipt = None
        deadline = time.monotonic() + 450
        while time.monotonic() < deadline:
            admission = call("GET", "commands/" + initial["operationId"])
            if admission["deliveries"][0]["state"] in (
                "failed",
                "unknown",
                "cancelled",
            ):
                raise RuntimeError(
                    "Initial native Global execution is terminal/uncertain; no retry"
                )
            goals = call("GET", "rooms/" + room + "/goals")["goals"]
            if goals:
                if len(goals) != 1:
                    raise RuntimeError("Unexpected goal fanout")
                goal = goals[0]
                plan = call("GET", "goals/" + goal["id"])["plan"]
                if plan:
                    if len(plan) != 1:
                        raise RuntimeError("Unexpected work fanout")
                    work = plan[0]
                    for candidate in units():
                        if candidate["agentId"] == work["owner"]:
                            worker_receipt = candidate
                    if worker_receipt:
                        started = (
                            Path(worker_receipt["workspace"]) / "cancel-started.json"
                        )
                        if started.exists():
                            namespace_pid = json.loads(started.read_text())["pid"]
                            candidates = []
                            for proc in Path("/proc").iterdir():
                                if not proc.name.isdigit():
                                    continue
                                try:
                                    if proc.stat().st_uid != worker_receipt["uid"]:
                                        continue
                                    status = proc.joinpath("status").read_text()
                                    ns = next(
                                        (
                                            line.split()[1:]
                                            for line in status.splitlines()
                                            if line.startswith("NSpid:")
                                        ),
                                        [],
                                    )
                                    argv = (
                                        proc.joinpath("cmdline")
                                        .read_bytes()
                                        .split(b"\0")
                                    )
                                    if (
                                        ns
                                        and int(ns[-1]) == namespace_pid
                                        and helper_code.encode() in argv
                                    ):
                                        fields = (
                                            proc.joinpath("stat").read_text().split()
                                        )
                                        candidates.append(
                                            {
                                                "pid": int(proc.name),
                                                "start": fields[21],
                                                "uid": worker_receipt["uid"],
                                                "namespacePid": namespace_pid,
                                                "workspace": worker_receipt[
                                                    "workspace"
                                                ],
                                            }
                                        )
                                except (FileNotFoundError, ProcessLookupError):
                                    continue
                            if len(candidates) != 1:
                                raise RuntimeError(
                                    "Cannot establish the exact sandbox-to-host helper identity"
                                )
                            helper = candidates[0]
                            saved(root / "owned-helper-before.json", helper)
                            pending = call(
                                "GET", "rooms/" + work["room"] + "/attention"
                            )["attention"]
                            attention = next(
                                (
                                    x
                                    for x in pending
                                    if x["attention"]["delivery"] == work["delivery"]
                                ),
                                None,
                            )
                            if attention:
                                break
            time.sleep(1)
        else:
            raise RuntimeError(
                "Bounded native initialization did not produce its owned helper/question"
            )
        original = call("GET", "commands/" + initial["operationId"])
        while original["deliveries"][0]["state"] not in (
            "completed",
            "failed",
            "unknown",
            "cancelled",
        ):
            if time.monotonic() >= deadline:
                raise RuntimeError("Initial Global turn remains unsettled")
            time.sleep(1)
            original = call("GET", "commands/" + initial["operationId"])
        if original["deliveries"][0]["state"] != "completed":
            raise RuntimeError("Initial Global did not complete delegation")
        saved(root / "original-question.json", attention)
        followup = {
            "operationId": "lifecycle-native-stop",
            "kind": "request",
            "audience": "room",
            "recipientId": global_id,
            "sourceEventId": accepted["event"]["id"],
            "body": "Cancel this exact qualification work now: "
            + work["id"]
            + ", goal "
            + goal["id"]
            + ". Call hollywood_work_cancel with its current revision and an explicit cancellation note. Then read that exact work once to observe native acknowledgement. "
            "Read the goal revision and request state cancelled even if work acknowledgement is still pending. Goal cancellation is durable and the service will reconcile its child acknowledgements. Leave the native coordination objective stopped/paused, not falsely complete. "
            "If still awaiting acknowledgement, state that exact fact and end without polling or scheduling. Do not answer the worker question or reassign/retry the work.",
        }
        stopped = message("stop", followup)
        if stopped["event"]["data"].get("goalReferenceId") != goal["id"]:
            raise RuntimeError("Global followup lost its original goal reference")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            current = call("GET", "work/" + work["id"])
            result = call("GET", "commands/" + followup["operationId"])
            if current["execution"]["state"] in ("unknown", "failed"):
                raise RuntimeError(
                    "Cancellation remains uncertain; original delivery held without replay"
                )
            aggregate = call("GET", "goals/" + goal["id"])
            if (
                current["execution"]["state"] == "cancelled"
                and result["deliveries"][0]["state"] == "completed"
                and aggregate["goal"]["state"] == "cancelled"
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Cancellation acknowledgement did not settle")
        if current["work"]["state"] != "cancelled":
            raise RuntimeError(
                "Work still claims cancellation pending after native stop acknowledgement"
            )
        for _ in range(20):
            if not live(helper["pid"], helper["start"]):
                break
            time.sleep(0.25)
        if live(helper["pid"], helper["start"]):
            raise RuntimeError("Native cancellation left its owned helper running")
        if (Path(worker_receipt["workspace"]) / "cancel-finished.txt").exists():
            raise RuntimeError("Deferred effect occurred")
        final_goal = call("GET", "goals/" + goal["id"])
        if final_goal["goal"]["state"] != "cancelled":
            raise RuntimeError("Global did not cancel the acknowledged goal")
        scope = attention["scope"]
        reply = {
            "operationId": "lifecycle-late-answer",
            "scope": scope,
            "response": {"answers": {"continue": {"answers": ["continue"]}}},
        }
        saved(root / "late-answer-intent.json", reply)
        call(
            "POST",
            "attention/" + scope["attentionId"] + "/response",
            reply,
            expected=409,
        )
        worker_state = Path(worker_receipt["workspace"]).parent / "state"
        native_stop = json.loads(
            (
                worker_state / ("goal-lifecycle-" + work["delivery"] + ".json")
            ).read_text()
        )
        if native_stop["after"]["status"] != "paused":
            raise RuntimeError("Stopped worker retains an active native goal")
        bindings = [
            call("GET", "deliveries/" + d)["nativeGoalBinding"]
            for d in (initial_delivery, stopped["deliveries"][0]["id"])
        ]
        if (
            bindings[0]["native_thread"] != bindings[1]["native_thread"]
            or bindings[0]["native_goal_id"] != bindings[1]["native_goal_id"]
        ):
            raise RuntimeError(
                "Global control replaced or forked its native coordination context"
            )
        policy = list(
            (Path(global_receipt["home"]) / "state").glob("goal-policy-*.json")
        )
        if not policy or not any(
            json.loads(p.read_text()).get("after", {}).get("status") == "paused"
            for p in policy
        ):
            raise RuntimeError(
                "Canonical goal cancellation did not pause its bound native coordination goal"
            )
        history = []
        cursor = 0
        for _ in range(10):
            page = call(
                "GET", "rooms/" + room + "/history?after=" + str(cursor) + "&limit=100"
            )
            history.extend(page["events"])
            cursor = page["nextCursor"]
            if len(page["events"]) < 100:
                break
        observations = [
            e["data"]["nativeGoal"]
            for e in history
            if e.get("data", {}).get("nativeType") == "goalState"
            and e["data"].get("deliveryId") == stopped["deliveries"][0]["id"]
        ]
        if not observations or observations[-1]["status"] != "paused":
            raise RuntimeError(
                "Final verified Global native goal status differs from its stop policy"
            )
        admin_records = [
            json.loads(p.read_text())
            for p in (Path(global_receipt["home"]) / "state").glob(
                "administration-*.json"
            )
        ]
        conflict_recovered = any(
            x.get("state") == "rejected" and x.get("status") == 409
            for x in admin_records
        )
        if spec.get("exerciseStaleGrant") and (
            not conflict_recovered
            or any(x.get("state") == "unconfirmed" for x in admin_records)
        ):
            raise RuntimeError(
                "Known membership conflict did not recover through authoritative inspection"
            )
        saved(
            root / "result.json",
            {
                "state": "passed-real-native-goal-cancellation",
                "authorityId": authority,
                "goalId": goal["id"],
                "workId": work["id"],
                "nativeWorkerGoalPaused": True,
                "globalSameContextAndGoalInstance": True,
                "globalResponsiveDuringWorkerQuestion": True,
                "globalCanonicalAndNativeGoalStopped": True,
                "workerAndExecutionCancelled": True,
                "ownedHelperStopped": True,
                "deferredEffectOccurred": False,
                "lateAnswerDenied": True,
                "externalEffectsUndone": False,
                "realNativeTurns": 3,
                "modelPolling": False,
                "knownMembershipConflictRecovered": conflict_recovered,
                "productionChanged": False,
                "physicalPhone": False,
            },
        )
        print("Actual native Global/worker cancellation passed.")
    finally:
        cleanup = []
        for worker in units():
            subprocess.run(
                ["systemctl", "stop", worker["unit"]],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["systemctl", "disable", worker["unit"]],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cleanup.append(worker["unit"])
        subprocess.run(
            ["systemctl", "stop", global_unit],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if helper and live(helper["pid"], helper["start"]):
            os.kill(helper["pid"], signal.SIGTERM)
            saved(
                root / "operator-helper-cleanup.json",
                {
                    "nativeCancellationQualified": False,
                    "originalOwnedHelper": helper,
                    "signal": "SIGTERM",
                    "originalRequestResubmitted": False,
                },
            )
        if api and api.poll() is None:
            api.terminate()
            try:
                api.wait(timeout=20)
            except subprocess.TimeoutExpired:
                api.kill()
                api.wait()
        saved(
            root / "cleanup.json",
            {
                "workerUnitsStoppedAndDisabled": cleanup,
                "globalUnitStopped": global_unit,
                "apiStopped": True,
                "productionChanged": False,
            },
        )


def cleanup_owned(spec):
    root = Path(spec["evidence"])
    intent = root / "enterprise/installation-intent.json"
    if not intent.exists():
        return
    authority = json.loads(intent.read_text())["authorityId"]
    for path in (Path("/var/lib/harness") / authority / "workers").glob(
        "*/provision-receipt.json"
    ):
        row = json.loads(path.read_text())
        if row["authorityId"] != authority or not row["unit"].startswith(
            "lax-worker-" + authority.replace("-", "")[:8] + "-"
        ):
            raise RuntimeError("Cleanup ownership differs from original qualification")
        subprocess.run(
            ["systemctl", "stop", row["unit"]],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["systemctl", "disable", row["unit"]],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    subprocess.run(
        [
            "systemctl",
            "stop",
            "lax-lifecycle-global-" + authority.replace("-", "")[:12],
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    if args.cleanup:
        cleanup_owned(spec)
    else:
        main(spec)
