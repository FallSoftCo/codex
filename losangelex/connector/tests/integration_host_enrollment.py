"""Actual HTTP/PostgreSQL host enrollment compatibility; no workers or models."""

import asyncio
import hashlib
import json
import os
import secrets
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from aiohttp import ClientSession, web
from hollywood_backbone.bootstrap import initialize
from hollywood_backbone.server import application
from hollywood_backbone.store import Store
from lax_connector.host_enrollment import fingerprint
from lax_connector.errors import ToolValidationError
from lax_connector.placement_control import view


async def main():
    os.umask(0o077)
    root = Path(os.environ["ENROLLMENT_EVIDENCE"])
    root.mkdir(mode=0o700)
    db = json.loads(Path(os.environ["ENROLLMENT_DATABASE_CONFIG"]).read_text())
    initialize(db, root / "authority-a", "R344 host enrollment A")
    initialize(db, root / "authority-b", "R344 host enrollment B")
    a = json.loads((root / "authority-a/installation-intent.json").read_text())
    b = json.loads((root / "authority-b/installation-intent.json").read_text())
    token = a["credentials"]["Owner"]["token"]
    store = Store(db)
    runner = web.AppRunner(application(store), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1]) + "/hollywood/v3/"
    calls, checks = [], []
    raw = Path("/etc/machine-id").read_bytes()
    legacy = hashlib.sha256(raw).hexdigest()
    normalized = hashlib.sha256(raw.strip()).hexdigest()
    assert legacy != normalized, "This reproduction requires the actual newline-terminated machine file"
    host, modern, wrong = [str(uuid4()) for _ in range(3)]
    target, alternate, unplaced = [str(uuid4()) for _ in range(3)]

    async with ClientSession() as session:
        async def call(method, path, payload=None, expected=200, credential=token):
            async with session.request(method, url + path, json=payload,
                                       headers={"Authorization": "Bearer " + credential}) as response:
                data = await response.json()
                calls.append({"method": method, "path": path, "status": response.status})
                assert response.status == expected, (path, response.status, expected, data)
                return data

        async def enroll(h, identity, fp, suffix, expected=200):
            return await call("POST", "placements", {
                "operationId": "r344:" + suffix, "hostId": h, "agentId": identity,
                "name": "Nonexecuting metadata fixture " + h[:8], "identityFingerprint": fp,
                "capabilities": {"metadataOnly": True},
            }, expected=expected)

        def connector(h=host, authority=None, transport=call):
            return SimpleNamespace(config={"hostId": h}, http=transport,
                                   captured_execution=lambda: {"request": {"authority": authority or a["authorityId"]}})

        try:
            for identity in (target, alternate, unplaced):
                await call("POST", "principals", {
                    "operationId": "r344:principal:" + identity, "id": identity,
                    "name": "Metadata-only peer " + identity[:8], "kind": "agent",
                    "enrollmentCredential": secrets.token_urlsafe(40),
                })
            await enroll(host, a["credentials"]["Global"]["principalId"], legacy, "old-host")
            empty = await call("GET", "placements/" + target)
            assert view(empty, a["authorityId"], target)["state"] == "not_enrolled"
            assert empty["placement"] is None and empty["hostId"] is None
            checks.append("Real un-enrolled/null placement is readable without TypeError")

            await enroll(host, target, normalized, "original-broken-control", expected=409)
            with store.pool.connection() as c:
                assert not c.execute("SELECT 1 FROM hb_placement WHERE agent=%s", (target,)).fetchone()
                original = c.execute("SELECT * FROM hb_placement WHERE agent=%s",
                                     (a["credentials"]["Global"]["principalId"],)).fetchone()
            checks.append("Original stripped-hash placement control fails409 with no target enrollment")

            accepted = await fingerprint(connector())
            assert accepted == legacy
            await enroll(host, target, accepted, "corrected-peer")
            with store.pool.connection() as c:
                assert c.execute("SELECT * FROM hb_placement WHERE agent=%s",
                                 (a["credentials"]["Global"]["principalId"],)).fetchone() == original
                assert c.execute("SELECT identity_fingerprint FROM hb_host WHERE id=%s",
                                 (host,)).fetchone()["identity_fingerprint"] == legacy
            checks.append("Native resolver reuses accepted raw fingerprint; new peer placed without changing host or original placement")

            await enroll(modern, alternate, normalized, "modern-host")
            assert await fingerprint(connector(modern)) == normalized
            checks.append("Normalized enrollment remains supported on a fresh host")

            await enroll(wrong, unplaced, "0" * 64, "other-physical-host")
            try:
                await fingerprint(connector(wrong))
            except ToolValidationError as e:
                assert e.code == "HOST_ENROLLMENT_MACHINE_MISMATCH"
            else:
                raise AssertionError("Different physical machine accepted")
            try:
                await fingerprint(connector(authority=b["authorityId"]))
            except PermissionError:
                pass
            else:
                raise AssertionError("Different authority accepted")
            checks.append("Different local-machine fingerprint and authority refused before peer placement")

            async def missing(method, path, payload=None):
                result = dict(await call(method, path, payload))
                result.pop("enrollment", None)
                return result
            try:
                await fingerprint(connector(transport=missing))
            except ToolValidationError as e:
                assert e.code == "HOST_ENROLLMENT_UNAVAILABLE"
            else:
                raise AssertionError("Missing enrollment evidence accepted")
            checks.append("Missing compatible projection fails closed without a guessed fingerprint")

            await call("GET", "hosts/" + host + "/admission", expected=403,
                       credential=b["credentials"]["Owner"]["token"])
            checks.append("Foreign-authority administrator cannot read host enrollment")
            await enroll(modern, target, normalized, "forbidden-move", expected=409)
            with store.pool.connection() as c:
                assert str(c.execute("SELECT host FROM hb_placement WHERE agent=%s",
                                     (target,)).fetchone()["host"]) == host
            checks.append("Existing peer cannot silently move to another host")
            result = {"checks": checks, "httpCalls": calls, "passed": True,
                      "proofScope": "Actual HTTP/PG and SDK resolver/parser; metadata principals only, no install/model/production changes"}
            (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
        finally:
            await runner.cleanup()
            store.close()


if __name__ == "__main__":
    asyncio.run(main())
