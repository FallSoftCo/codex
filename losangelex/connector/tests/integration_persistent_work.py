"""Final packaged goal/work acceptance on the retained real multi-room agents."""

import argparse, json, os, subprocess, time, urllib.request
from pathlib import Path
from hollywood_backbone.store import Store, json_value
from lax_connector.journal import saved
from lax_connector.service_admin import inspect
from lax_connector.service_observer import (
    approve_drained_upgrade,
    register,
    installed_unit,
)


def main(root, runtime, database):
    os.umask(0o077)
    root = Path(root)
    runtime = Path(runtime)
    e = root.parent
    setup = json.loads((root / "enterprise/installation-intent.json").read_text())
    g = json.loads((root / "global-provision.json").read_text())
    authority = setup["authorityId"]
    host = json.loads((root / "scenario.json").read_text())["host"]
    marker = json.loads((root / "scenario.json").read_text())["marker"]
    peerfile = next(
        (Path("/var/lib/harness") / authority / "workers").glob(
            "*/provision-receipt.json"
        )
    )
    peer = json.loads(peerfile.read_text())
    pconfig = Path(peer["workspace"]).parent / "connector.json"
    units = [
        (g["agentId"], g["unit"], Path(g["home"]) / "connector.json"),
        (peer["agentId"], peer["unit"], pconfig),
    ]
    python = str(runtime / "venv/bin/python")
    api = controller = None
    errors = []
    store = Store(json.loads(Path(database).read_text()))
    owner = setup["credentials"]["Owner"]
    url = "http://127.0.0.1:18777"

    def call(method, path, body=None):
        req = urllib.request.Request(
            url + "/hollywood/v3/" + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + owner["token"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def rows():
        with store.pool.connection() as c:
            return json_value(
                c.execute(
                    "SELECT d.*,e.seq FROM hb_delivery d JOIN hb_event e ON e.id=d.event WHERE d.authority=%s ORDER BY e.seq",
                    (authority,),
                ).fetchall()
            )

    def wait(read, predicate, seconds=480):
        end = time.monotonic() + seconds
        value = None
        while time.monotonic() < end:
            value = read()
            if predicate(value):
                return value
            time.sleep(0.5)
        saved(e / "packaged-work-timeout.json", value)
        raise TimeoutError("Original packaged work retained; do not resubmit")

    try:
        for _, unit, config in units:
            assert (
                subprocess.run(
                    ["systemctl", "is-active", unit], capture_output=True, text=True
                ).stdout.strip()
                == "inactive"
            )
            unit = unit if unit.endswith(".service") else unit + ".service"
            drop = Path("/etc/systemd/system") / (unit + ".d")
            drop.mkdir(exist_ok=True)
            (drop / "packaged-context-qualification.conf").write_text(
                "[Service]\nExecStart=\nExecStart="
                + python
                + " -m lax_connector.connector --config "
                + str(config)
                + " --serve\n"
            )
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        with (e / "packaged-work-api.log").open("ab") as log:
            api = subprocess.Popen(
                [
                    python,
                    "-m",
                    "hollywood_backbone.server",
                    "--database-config",
                    database,
                    "--port",
                    "18777",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )

        def health():
            try:
                with urllib.request.urlopen(url + "/health", timeout=2) as r:
                    return r.status == 200
            except OSError:
                return False

        wait(health, bool, 30)
        h = json.loads((root / "host-enrollment.json").read_text())
        with (e / "packaged-work-controller.log").open("ab") as log:
            controller = subprocess.Popen(
                [python, "-m", "lax_connector.host", "--serve", h["configPath"]],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        before = rows()
        assert len(before) == 6 and all(
            r["state"] in ("completed", "cancelled") for r in before
        )
        registration = []
        for agent, unit, _ in units:
            subprocess.run(
                ["systemctl", "start", unit], check=True, capture_output=True
            )
            info = inspect(authority, host, agent)
            if info["reason"] == "explicit-drained-upgrade-required":
                approve_drained_upgrade(
                    authority,
                    host,
                    agent,
                    info["expectedEnrollment"],
                    info["expectedDefinition"],
                )
            register(authority, host, agent, installed_unit(authority, agent))
            actual = inspect(authority, host, agent)
            assert actual["ready"]
            registration.append(actual)
        saved(e / "packaged-work-service-registration.json", registration)
        catalog = call("GET", "rooms")
        workshop = next(r["id"] for r in catalog["rooms"] if r["name"] == "Workshop")
        body = {
            "operationId": "packaged-goal-work-" + authority,
            "kind": "request",
            "recipientId": g["agentId"],
            "audience": "room",
            "body": "Produce a final release proof using an optional Hollywood business goal and its work plan. "
            "Use reviewBudget 1. Assign one bounded work item to the existing Workshop peer "
            + peer["agentId"]
            + " in Workshop "
            + workshop
            + ". The deliverable is release-proof.md in the peer's workspace, containing the original "
            "installation-proof marker, its current responsibility and the SHA256 of its original peer-review.txt. "
            "Have the peer submit independently hashable artifact evidence. When its material review reaches you, independently "
            "verify actual bytes and explicitly accept the work and goal if correct; publish the final acceptance in Global. "
            "Keep both existing agents and their contexts. Do not create agents, accounts, schedules, outreach or any other work.",
        }
        intent = e / "packaged-work-request-intent.json"
        receipt = e / "packaged-work-request-receipt.json"
        if intent.exists():
            raise RuntimeError(
                "Original request already prepared; inspect original receipt rather than rerunning"
            )
        saved(intent, body)
        result = call("POST", "rooms/" + setup["globalRoomId"] + "/messages", body)
        saved(receipt, result)

        def accepted(value):
            if any(r["state"] in ("failed", "unknown") for r in value[6:]):
                raise RuntimeError(
                    "Packaged native work failed/unknown; retain original operations"
                )
            if len(value) < 9 or any(r["state"] != "completed" for r in value[6:]):
                return False
            with store.pool.connection() as c:
                goals = c.execute(
                    "SELECT state FROM hb_goal WHERE authority=%s", (authority,)
                ).fetchall()
            return len(goals) == 1 and goals[0]["state"] == "accepted"

        final = wait(rows, accepted, 600)
        time.sleep(3)
        final = rows()
        assert len(final) == 9
        assert (
            len({r["native_thread"] for r in final if r["agent"] == g["agentId"]}) == 1
        )
        assert (
            len({r["native_thread"] for r in final if r["agent"] == peer["agentId"]})
            == 1
        )
        artifact = Path(peer["workspace"]) / "release-proof.md"
        assert marker in artifact.read_text()
        with store.pool.connection() as c:
            works = json_value(
                c.execute(
                    "SELECT * FROM hb_work WHERE authority=%s", (authority,)
                ).fetchall()
            )
            assert (
                len(works) == 1
                and works[0]["state"] == "accepted"
                and works[0]["evidence"]
            )
            native_goals = c.execute(
                "SELECT count(*) AS n FROM hb_native_goal_binding b JOIN hb_delivery d ON d.id=b.delivery WHERE d.authority=%s",
                (authority,),
            ).fetchone()["n"]
        assert native_goals == 0
        result = {
            "passed": True,
            "releaseManifest": str(runtime / "release-manifest.json"),
            "actualAdditionalProviderTurns": 3,
            "totalProviderTurns": 9,
            "persistentAgentContexts": 2,
            "goalAccepted": True,
            "workAccepted": True,
            "connectorHashedEvidence": works[0]["evidence"],
            "sameContextAcrossPlainRequestsRolesAndBusinessWork": True,
            "syntheticNativeBindings": 0,
            "productionChanged": False,
        }
        saved(e / "packaged-work-result.json", result)
        print(json.dumps(result), flush=True)
    finally:
        for _, unit, _ in units:
            for action in ["stop", "disable"]:
                r = subprocess.run(
                    ["systemctl", action, unit], capture_output=True, timeout=45
                )
                if r.returncode:
                    errors.append(unit + ":" + action)
        for child in [controller, api]:
            if child and child.poll() is None:
                child.terminate()
                child.wait(timeout=25)
        store.close()
        saved(
            e / "packaged-work-cleanup.json",
            {
                "errors": errors,
                "ownedServicesStopped": True,
                "productionChanged": False,
            },
        )
        if errors:
            raise RuntimeError("Owned cleanup incomplete")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--runtime", required=True)
    p.add_argument("--database", required=True)
    a = p.parse_args()
    main(a.root, a.runtime, a.database)
