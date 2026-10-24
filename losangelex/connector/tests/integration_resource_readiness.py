"""Actual Hollywood HTTP/PostgreSQL and Unix UID root-access qualification.

No model is called. A disposable authority uses an existing stopped QA Unix
identity for read-only probes; this is not a fresh installation/model proof.
"""

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import time
import urllib.error
from pathlib import Path
from uuid import uuid4

from aiohttp import web
from hollywood_backbone.server import application
from hollywood_backbone.store import Store
from lax_connector.collaboration_bridge import Held, digest
from lax_connector.host import request
from lax_connector.journal import saved
from lax_connector.purpose_install import protected
from lax_connector.purpose_resource_readiness import verify


async def qualify(args):
    root, output = Path(args.root), Path(args.output)
    assert os.geteuid() == 0
    if args.resume_fixture:
        assert output.is_dir() and root.is_dir()
    else:
        assert not root.exists() and not output.exists()
        output.mkdir(mode=0o700)
        root.mkdir(mode=0o755)
        root.chmod(0o755)
    source = protected(Path(args.service_installation))
    uid, gid = source["uid"], source["gid"]
    assert uid != 0
    value = {
        **source,
        "authorityId": str(uuid4()),
        "agentId": str(uuid4()),
        "hostId": str(uuid4()),
        "interpreter": str(Path(args.runtime) / "bin/python"),
    }
    identity = {
        "authorityId": value["authorityId"],
        "globalRoomId": str(uuid4()),
        "name": "Disposable resource readiness qualification",
        "credentials": {
            name: {"principalId": str(uuid4()), "token": secrets.token_urlsafe(40)}
            for name in ("Owner", "Global")
        },
    }
    identity["credentials"]["Global"]["principalId"] = value["agentId"]
    if args.resume_fixture:
        original_fixture = protected(output / "fixture.json")
        value = original_fixture["value"]
        assert value["uid"] == uid and value["gid"] == gid
        assert value["interpreter"] == str(Path(args.runtime) / "bin/python")
        identity = protected(output / "private-identity.json")
    else:
        saved(output / "private-identity.json", identity)
    baseline = protected(Path(args.protected_baseline))["protectedPids"]

    def pids():
        return {
            u: subprocess.check_output(
                ["systemctl", "show", u, "-p", "MainPID", "--value"], text=True
            ).strip()
            for u in baseline
        }

    assert pids() == baseline
    store = Store(protected(Path(args.database_config)))
    runner = web.AppRunner(application(store), access_log=None)
    checks, refusals = {}, {}
    try:
        if not args.resume_fixture:
            saved(
                output / "bootstrap.json",
                store.bootstrap(value["authorityId"], identity["name"], identity),
            )
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])

        async def http(method, route, payload=None):
            return await asyncio.to_thread(
                request,
                url,
                identity["credentials"]["Owner"]["token"],
                method,
                route,
                payload,
            )

        if args.resume_fixture:
            registrations = original_fixture["registrations"]
            assert len(registrations) == 10
            roots = [(Path(r["path"]), r["canWrite"]) for r in registrations]
            config = original_fixture["config"]
            locked = root / "locked-parent"
            # Exact operator-owned fixture directories only. No product ACL repair.
            root.chmod(0o755)
            roots[2][0].chmod(0o555)
            locked.chmod(0o700)
            policy = await http(
                "GET", "hosts/" + value["hostId"] + "/collaboration-bridge"
            )
            rows = []
            after = None
            while True:
                route = (
                    "agents/"
                    + value["agentId"]
                    + "/resources?executionHost="
                    + value["hostId"]
                    + "&limit=8"
                )
                if after:
                    route += "&after=" + after
                page = await http("GET", route)
                rows.extend(page["resources"])
                after = page["nextCursor"]
                if after is None:
                    break
            assert {str(r["workspace"]["id"]) for r in rows} == {
                r["id"] for r in registrations
            }
            assert all(
                r["grant"]["revision"] == 1 and r["grant"]["state"] == "active"
                for r in rows
            ), "Inspect original advanced fixture; no mutation replay"
        else:
            await http(
                "POST",
                "placements",
                {
                    "operationId": "readiness-r319:placement",
                    "hostId": value["hostId"],
                    "name": "Disposable root-access fixture",
                    "identityFingerprint": digest(value["hostId"]),
                    "capabilities": {"resourceReadinessOnly": True},
                    "agentId": value["agentId"],
                },
            )
            policy = await http(
                "GET", "hosts/" + value["hostId"] + "/collaboration-bridge"
            )
            environment = digest({"hostId": value["hostId"], "environmentId": "local"})
            locked = root / "locked-parent"
            locked.mkdir(mode=0o700)
            roots = [
                (root / "private", True),
                (locked / "shared", True),
                (root / "read-only", False),
            ]
            roots.extend((root / ("resource-" + str(i)), True) for i in range(7))
            registrations = []
            for index, (path, writable) in enumerate(roots):
                path.mkdir(mode=0o700 if writable else 0o555)
                path.chmod(0o700 if writable else 0o555)
                if writable:
                    os.chown(path, uid, gid)
                info = path.stat()
                workspace = str(uuid4())
                state = {
                    "path": str(path),
                    "id": workspace,
                    "revision": 1,
                    "grantRevision": 1,
                    "canWrite": writable,
                }
                await http(
                    "PUT",
                    "hosts/" + value["hostId"] + "/physical-workspaces/" + workspace,
                    {
                        "operationId": "readiness-r319:root:" + str(index),
                        "revision": 0,
                        "state": "active",
                        "rootPath": str(path),
                        "environmentSha256": environment,
                        "rootIdentitySha256": digest(
                            {
                                "hostId": value["hostId"],
                                "environmentSha256": environment,
                                "device": info.st_dev,
                                "inode": info.st_ino,
                            }
                        ),
                        "registrationSha256": digest(state),
                    },
                )
                await http(
                    "PUT",
                    "physical-workspaces/"
                    + workspace
                    + "/agent-grants/"
                    + value["agentId"],
                    {
                        "operationId": "readiness-r319:grant:" + str(index),
                        "revision": 0,
                        "workspaceRevision": 1,
                        "executionHost": value["hostId"],
                        "state": "active",
                        "canRead": True,
                        "canWrite": writable,
                    },
                )
                registrations.append(state)
            config = {"workspace": str(roots[0][0])}
            saved(
                output / "fixture.json",
                {"value": value, "config": config, "registrations": registrations},
            )

        def read(method, route):
            return request(
                url, identity["credentials"]["Owner"]["token"], method, route
            )

        async def probe():
            return await asyncio.to_thread(verify, value, config, read, policy)

        async def denied(name):
            try:
                await probe()
            except (PermissionError, Held) as error:
                refusals[name] = {
                    "type": type(error).__name__,
                    "message": str(error)[-4096:],
                }
                return True
            return False

        old = subprocess.run(
            [
                "runuser",
                "-u",
                value["linuxUser"],
                "--",
                value["interpreter"],
                "-I",
                "-B",
                "-c",
                "import os,sys; assert os.geteuid()==int(sys.argv[1]); "
                "assert os.access(sys.argv[2],os.R_OK|os.W_OK|os.X_OK)",
                str(uid),
                config["workspace"],
            ],
            capture_output=True,
        )
        checks["old_private_only_check_passes"] = old.returncode == 0
        checks["shared_parent_inaccessibility_refused"] = await denied("locked_parent")
        # This changes only the operator-owned disposable fixture parent.
        locked.chmod(0o755)
        result, private = await probe()
        checks["all10_resources_verified_across_pagination"] = (
            len(result["resources"]) == 10 and private["root"] == config["workspace"]
        )
        checks["read_only_grant_does_not_require_write"] = any(
            r["root"] == str(roots[2][0]) and r["canWrite"] is False
            for r in result["resources"]
        )
        readonly = registrations[2]
        await http(
            "PUT",
            "physical-workspaces/"
            + readonly["id"]
            + "/agent-grants/"
            + value["agentId"],
            {
                "operationId": "readiness-r319:readonly-write-mismatch",
                "revision": 1,
                "workspaceRevision": 1,
                "executionHost": value["hostId"],
                "state": "active",
                "canRead": True,
                "canWrite": True,
            },
        )
        checks["canonical_write_grant_with_OS_write_denial_refused"] = await denied(
            "write_denied"
        )
        await http(
            "PUT",
            "physical-workspaces/"
            + readonly["id"]
            + "/agent-grants/"
            + value["agentId"],
            {
                "operationId": "readiness-r319:revoke-fixture",
                "revision": 2,
                "workspaceRevision": 1,
                "executionHost": value["hostId"],
                "state": "revoked",
                "canRead": False,
                "canWrite": False,
            },
        )
        result, _ = await probe()
        checks["revoked_grant_does_not_become_permission"] = len(
            result["resources"]
        ) == 9 and all(r["workspaceId"] != readonly["id"] for r in result["resources"])
        shared = roots[1][0]
        original = shared.with_name("shared-original-retained")
        shared.rename(original)
        try:
            shared.mkdir(mode=0o700)
            os.chown(shared, uid, gid)
            checks["changed_physical_incarnation_refused"] = await denied(
                "changed_root"
            )
        finally:
            shared.rmdir()
            original.rename(shared)
        final, _ = await probe()
        checks["original_physical_root_restored_and_verified"] = final == result
        try:
            await asyncio.to_thread(
                request,
                url,
                "not-an-enrolled-token",
                "GET",
                "agents/"
                + value["agentId"]
                + "/resources?executionHost="
                + value["hostId"]
                + "&limit=8",
            )
            checks["unenrolled_token_refused"] = False
        except urllib.error.HTTPError as error:
            checks["unenrolled_token_refused"] = error.code in (401, 403)
        with store.pool.connection() as c:
            executors = c.execute(
                "SELECT count(*) AS n FROM hb_executor WHERE authority=%s",
                (value["authorityId"],),
            ).fetchone()["n"]
            deliveries = c.execute(
                "SELECT count(*) AS n FROM hb_delivery WHERE authority=%s",
                (value["authorityId"],),
            ).fetchone()["n"]
        checks["no_native_executor_or_delivery_created"] = executors == deliveries == 0
        checks["protected_production_pids_unchanged"] = pids() == baseline
        evidence = {
            "schema": "lax-resource-readiness-qualification/v1",
            "at": time.time(),
            "passed": all(checks.values()),
            "checks": checks,
            "refusals": refusals,
            "actualUID": uid,
            "authority": value["authorityId"],
            "finalResourceAccess": final,
            "modelCalls": 0,
            "nativeExecutors": executors,
            "deliveries": deliveries,
            "listener": "Ephemeral loopback only; closed in finally.",
            "scope": "Actual Hollywood authenticated HTTP/PostgreSQL and actual installed "
            "Unix UID. Fresh disposable authority, existing stopped QA Unix "
            "identity. Substrate evidence; not clean installation/model proof.",
        }
        saved(output / "result.json", evidence)
        print(
            json.dumps(
                {
                    "passed": evidence["passed"],
                    "checks": checks,
                    "result": str(output / "result.json"),
                }
            ),
            flush=True,
        )
        assert evidence["passed"]
    finally:
        await runner.cleanup()
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "runtime",
        "root",
        "output",
        "service-installation",
        "protected-baseline",
        "database-config",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--resume-fixture", action="store_true")
    asyncio.run(qualify(parser.parse_args()))


if __name__ == "__main__":
    main()
