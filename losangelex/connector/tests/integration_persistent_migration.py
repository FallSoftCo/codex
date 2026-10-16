"""Exercise retained native history adoption and actual HTTP permission boundaries."""

import asyncio, json, os, shutil, subprocess, time, urllib.request, urllib.error, secrets
from pathlib import Path
from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.store import Store, digest
from lax_connector.rpc import AppServer
from lax_connector.native_goals import external_admission
from lax_connector.journal import saved


async def legacy_setup(config, thread, fixture):
    async def ignore(*args):
        pass

    rpc = AppServer(
        config["binary"], Path(config["codexHome"]), fixture / "native", ignore, ignore
    )
    try:
        await rpc.start()
        await external_admission(rpc, False)
        before = await rpc.call("thread/goal/get", {"threadId": thread})
        objective = "Synthetic legacy ongoing role for retained-context migration qualification only."
        if before["goal"]:
            assert before["goal"]["objective"] == objective
            return {
                "bindingKind": "role",
                "nativeThread": thread,
                "nativeGoalId": before["goalId"],
                "objective": objective,
            }
        result = await rpc.call(
            "thread/goal/set",
            {
                "threadId": thread,
                "expectedGoalId": None,
                "origin": "automatic",
                "objective": objective,
                "status": "active",
            },
        )
        return {
            "bindingKind": "role",
            "nativeThread": thread,
            "nativeGoalId": result["goalId"],
            "objective": objective,
        }
    finally:
        await rpc.close()


def main(root, runtime, database):
    os.umask(0o077)
    root = Path(root)
    runtime = Path(runtime)
    e = root.parent
    setup = json.loads((root / "enterprise/installation-intent.json").read_text())
    g = json.loads((root / "global-provision.json").read_text())
    config = json.loads((Path(g["home"]) / "connector.json").read_text())
    context = json.loads((Path(config["state"]) / "agent-context.json").read_text())
    original = json.loads(
        (
            Path(config["state"]) / ("context-" + context["contextId"] + ".json")
        ).read_text()
    )
    fixture = Path(g["home"]) / "state/migration-fixture"
    fixture.mkdir(mode=0o700, exist_ok=True)
    os.chown(fixture, g["uid"], g["uid"])
    cfg = {**config, "state": str(fixture)}
    fixture_config = fixture / "connector.json"
    saved(fixture_config, cfg)
    os.chown(fixture_config, g["uid"], g["uid"])
    legacy_context = {
        **original,
        "scope": [
            setup["authorityId"],
            g["agentId"],
            setup["globalRoomId"],
            "room",
            "room",
            config["workspace"],
        ],
    }
    record = fixture / ("context-" + context["contextId"] + ".json")
    saved(record, legacy_context)
    os.chown(record, g["uid"], g["uid"])
    # Native metadata only; use the actual completed Global context, no turn/start.
    local_driver = fixture / "integration_persistent_migration.py"
    shutil.copyfile(__file__, local_driver)
    os.chown(local_driver, g["uid"], g["uid"])
    script = e / "legacy-role-setup.py"
    script.write_text(
        "import asyncio,json,sys\nsys.path.insert(0,"
        + repr(str(fixture))
        + ")\nfrom integration_persistent_migration import legacy_setup\nfrom pathlib import Path\nc=json.loads(Path("
        + repr(str(fixture_config))
        + ").read_text())\nr=asyncio.run(legacy_setup(c,"
        + repr(original["nativeThread"])
        + ",Path("
        + repr(str(fixture))
        + ")))\nPath("
        + repr(str(fixture / "binding.json"))
        + ").write_text(json.dumps(r))\n"
    )
    script.chmod(0o644)
    # Evidence directories are protected; a same-owner task script lives in its fixture.
    local = fixture / "setup.py"
    shutil.copyfile(script, local)
    os.chown(local, g["uid"], g["uid"])
    python = str(runtime / "venv/bin/python")
    before_turns = sum(
        json.loads(line).get("payload", {}).get("type") == "task_started"
        for f in (Path(config["codexHome"]) / "sessions").rglob("*.jsonl")
        for line in f.read_text().splitlines()
    )
    child = subprocess.run(
        ["runuser", "-u", g["linuxUser"], "--", python, str(local)],
        capture_output=True,
        text=True,
    )
    saved(
        e / "migration-setup-process-result.json",
        {
            "returnCode": child.returncode,
            "stdout": child.stdout,
            "stderr": child.stderr,
        },
    )
    child.check_returncode()
    binding = json.loads((fixture / "binding.json").read_text())
    path = fixture / ("native-goal-" + context["contextId"] + ".json")
    saved(path, binding)
    os.chown(path, g["uid"], g["uid"])
    command = [
        "runuser",
        "-u",
        g["linuxUser"],
        "--",
        python,
        "-m",
        "lax_connector.agent_context",
        "--config",
        str(fixture_config),
        "--authority-id",
        setup["authorityId"],
        "--adopt-context",
        context["contextId"],
        "--retire-legacy-role-goal",
    ]
    r = subprocess.run(command, capture_output=True, text=True, check=True)
    migration = json.loads(r.stdout)
    saved(e / "legacy-adoption-receipt.json", migration)
    assert migration["nativeThread"] == original["nativeThread"]
    assert json.loads(record.read_text()) == legacy_context
    retirement = json.loads(
        (fixture / ("retired-role-goal-" + context["contextId"] + ".json")).read_text()
    )
    assert (
        retirement["after"]["goal"]["status"] == "paused"
        and retirement["modelTurnsStarted"] == 0
    )
    after_turns = sum(
        json.loads(line).get("payload", {}).get("type") == "task_started"
        for f in (Path(config["codexHome"]) / "sessions").rglob("*.jsonl")
        for line in f.read_text().splitlines()
    )
    assert before_turns == after_turns

    # Reopen only the owned private API; all model services remain stopped.
    api = None
    url = "http://127.0.0.1:18777/hollywood/v3/"
    owner = setup["credentials"]["Owner"]
    external = json.loads((root / "external-credential.json").read_text())
    second = json.loads((root / "second-human.json").read_text())

    def call(method, path, body=None, credential=None):
        request = urllib.request.Request(
            url + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + (credential or owner)["token"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    def denied(method, path, body=None, credential=None):
        try:
            call(method, path, body, credential)
        except urllib.error.HTTPError as error:
            assert error.code in (403, 409)
            return error.code
        raise AssertionError("Unauthorized operation accepted")

    try:
        with (e / "migration-http-api.log").open("ab") as log:
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
        for _ in range(100):
            assert api.poll() is None
            try:
                call("GET", "rooms")
                break
            except urllib.error.URLError:
                time.sleep(0.1)
        global_room = setup["globalRoomId"]
        catalog = call("GET", "rooms")
        workshop = next(r["id"] for r in catalog["rooms"] if r["name"] == "Workshop")
        assert denied("GET", "rooms/" + global_room, credential=second) == 403
        other = initialize(
            json.loads(Path(database).read_text()),
            e / "foreign-authority",
            "Foreign isolation QA",
        )
        foreign_setup = json.loads(
            (e / "foreign-authority/installation-intent.json").read_text()
        )
        assert (
            denied(
                "GET",
                "rooms/" + workshop,
                credential=foreign_setup["credentials"]["Owner"],
            )
            == 403
        )
        private_marker = "PRIVATE_" + secrets.token_hex(12)
        external_id = external["principalId"]
        call(
            "POST",
            "rooms/" + workshop + "/messages",
            {
                "operationId": "private-isolation-" + setup["authorityId"],
                "kind": "message",
                "audience": "direct",
                "recipientId": external_id,
                "body": private_marker,
            },
        )
        visible = call(
            "GET",
            "rooms/" + workshop + "/history?before=9223372036854775807&limit=100",
            credential=second,
        )
        assert private_marker not in json.dumps(visible)
        assert (
            denied(
                "PUT",
                "agents/" + g["agentId"] + "/communication",
                {
                    "operationId": "native-credential-grant-denied",
                    "credentialDigest": digest(config["token"]),
                    "allowRequests": True,
                },
            )
            == 403
        )
        # Original completed native source cannot write a new effect.
        source = next(
            json.loads(f.read_text())["scope"]
            for f in Path(config["state"]).glob("effects-*.json")
        )
        fields = (
            "authorityId",
            "agentId",
            "hostId",
            "deliveryId",
            "claimId",
            "generation",
            "requestId",
            "nativeThread",
            "nativeTurn",
            "callId",
            "tool",
            "argumentsDigest",
            "roleRevision",
            "contextId",
            "nativeGoalId",
        )
        header = json.dumps(
            {"schema": "hollywood-native-source/v2", **{k: source[k] for k in fields}}
        )
        request = urllib.request.Request(
            url + "rooms/" + global_room + "/messages",
            method="POST",
            data=json.dumps(
                {
                    "operationId": "stale-source-denied",
                    "kind": "message",
                    "body": "Must never be accepted.",
                }
            ).encode(),
            headers={
                "Authorization": "Bearer " + config["token"],
                "Content-Type": "application/json",
                "X-Hollywood-Native-Source": header,
            },
        )
        try:
            urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            assert error.code == 409
        else:
            raise AssertionError("Completed native source admitted a new effect")
        result = {
            "passed": True,
            "retainedOriginalNativeThread": original["nativeThread"],
            "legacyRoleGoalRetired": True,
            "legacyContextRecordUnchanged": True,
            "migrationProviderTurns": 0,
            "sameAuthorityRoomIsolation": True,
            "foreignAuthorityIsolation": True,
            "privateAudienceIsolation": True,
            "nativeCredentialExternalEnrollmentDenied": True,
            "staleNativeEffectDenied": True,
            "productionChanged": False,
        }
        saved(e / "migration-and-permissions-result.json", result)
        print(json.dumps(result))
    finally:
        if api and api.poll() is None:
            api.terminate()
            api.wait(timeout=20)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--runtime", required=True)
    p.add_argument("--database", required=True)
    a = p.parse_args()
    main(a.root, a.runtime, a.database)
