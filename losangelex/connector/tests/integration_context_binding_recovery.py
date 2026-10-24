"""Real canonical HTTP/PG bootstrap metadata recovery with injected transport loss.

The context threads are scripted identifiers. This proves no model semantics or
native execution; it exercises the actual SDK request journal and Hollywood API.
"""

import argparse
import asyncio
import json
import os
import secrets
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from aiohttp import web
from hollywood_backbone.server import application
from hollywood_backbone.store import Store
from lax_connector.context_runtime import ContextRunner, ContextAgent
from lax_connector.errors import HttpFailure
from lax_connector.journal import saved
from lax_connector.purpose_install import protected


async def run(args):
    root = Path(args.output)
    assert not root.exists()
    root.mkdir(mode=0o700)
    identity = {
        "authorityId": str(uuid4()),
        "globalRoomId": str(uuid4()),
        "name": "Bounded original bootstrap binding recovery",
        "credentials": {
            n: {"principalId": str(uuid4()), "token": secrets.token_urlsafe(40)}
            for n in ("Owner", "Global")
        },
    }
    saved(root / "private-identity.json", identity)
    agent, host = identity["credentials"]["Global"]["principalId"], str(uuid4())
    tokens = {p: secrets.token_urlsafe(40) for p in ("reader", "writer", "responder")}
    from hollywood_backbone.store import digest

    store = Store(protected(Path(args.database_config)))
    runner = web.AppRunner(application(store), access_log=None)
    counts, traces, checks = {}, [], {}
    try:
        saved(
            root / "bootstrap.json",
            store.bootstrap(identity["authorityId"], identity["name"], identity),
        )
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])
        async with __import__("aiohttp").ClientSession() as session:

            async def http(token, method, route, payload=None):
                async with session.request(
                    method,
                    url + "/hollywood/v3/" + route,
                    json=payload,
                    headers={"Authorization": "Bearer " + token},
                ) as response:
                    value = await response.json()
                    if response.status != 200:
                        raise HttpFailure(
                            response.status,
                            value.get("error", ""),
                            code=value.get("code"),
                            next_action=value.get("next"),
                        )
                    return value

            async def admin(method, route, payload=None):
                return await http(
                    identity["credentials"]["Owner"]["token"], method, route, payload
                )

            await admin(
                "POST",
                "placements",
                {
                    "operationId": "binding-recovery:placement",
                    "hostId": host,
                    "name": "Scripted context metadata fixture",
                    "identityFingerprint": digest(host),
                    "capabilities": {"metadataOnly": True},
                    "agentId": agent,
                },
            )
            context_ids = {p: str(uuid4()) for p in tokens}
            saved(root / "private-context-fixture.json", {
                "agent": agent, "host": host, "tokens": tokens, "contextIds": context_ids,
                "modelCallsAllowed": 0, "operationScope": "canonical bootstrap metadata only",
            })
            await admin(
                "PUT",
                "agents/" + agent + "/context-system",
                {
                    "operationId": "binding-recovery:contexts",
                    "hostId": host,
                    "workspaceId": str(uuid4()),
                    "bindings": [
                        {
                            "purpose": p,
                            "contextId": context_ids[p],
                            "credentialDigest": digest(t),
                        }
                        for p, t in tokens.items()
                    ],
                },
            )

            def sdk(purpose, fault=None):
                state = root / purpose
                state.mkdir()
                counts[purpose] = {"POST": 0, "GET": 0, "forwardedPOST": 0}

                async def client(p, method, route, payload=None):
                    counts[purpose][method] += 1
                    if method == "POST":
                        if fault == "before_commit" and counts[purpose]["POST"] == 1:
                            raise TimeoutError(
                                "Injected transport loss before server admission"
                            )
                        counts[purpose]["forwardedPOST"] += 1
                    wire_agent = SimpleNamespace(
                        session=session,
                        config={"agentId": agent, "tokens": tokens, "hollywoodUrl": url},
                    )
                    result = await ContextAgent.http(
                        wire_agent, p, method, route, payload
                    )
                    if (
                        method == "POST"
                        and fault == "after_commit"
                        and counts[purpose]["POST"] == 1
                    ):
                        raise TimeoutError(
                            "Injected SDK-boundary result loss after real server commit"
                        )
                    return result

                return SimpleNamespace(
                    state=state,
                    config={"agentId": agent},
                    purpose=purpose,
                    thread="scripted-existing-native-thread-" + purpose,
                    turn=None,
                    agent=SimpleNamespace(http=client),
                    trace=lambda event, value: traces.append({"event": event, **value}),
                )

            writer = sdk("writer", "before_commit")
            binding = {
                "runtimeProtocol": "lax-purpose-runtime/v3",
                "workScheduling": 2,
                "toolCompletion": 1,
                "nativeActionRetention": 1,
            }
            operation = "bind:original-writer-before-commit"
            try:
                await ContextRunner.request(
                    writer, "bind", binding, operation=operation, turn="bootstrap"
                )
                checks["precommit_loss_retains_unaccepted_original_intent"] = False
            except HttpFailure as error:
                checks["precommit_loss_retains_unaccepted_original_intent"] = (
                    error.status == 404 and error.code == "CONTEXT_OPERATION_NOT_FOUND"
                )
            result = await ContextRunner.request(
                writer, "bind", binding, operation=operation, turn="bootstrap"
            )
            checks["same_original_bind_recovers_without_new_native_identity"] = (
                result["nativeThread"] == writer.thread
                and result["contextId"] == context_ids["writer"]
                and result["nativeActionRetention"] == 1
                and counts["writer"]["forwardedPOST"] == 1
            )
            journals = list(writer.state.glob("operation-*.json"))
            journal = json.loads(journals[0].read_text())
            checks["original_journal_keeps_recovery_and_accepted_receipt"] = (
                len(journals) == 1
                and journal["state"] == "accepted"
                and journal["bindRecovery"]["count"] == 1
                and journal["request"]["operationId"] == operation
            )

            reader = sdk("reader", "after_commit")
            result = await ContextRunner.request(
                reader,
                "bind",
                {
                    "runtimeProtocol": "lax-purpose-runtime/v3",
                    "workScheduling": 2,
                    "toolCompletion": 1,
                },
                operation="bind:original-reader-after-commit",
                turn="bootstrap",
            )
            checks["committed_response_loss_uses_original_GET_no_second_POST"] = (
                result["nativeThread"] == reader.thread
                and counts["reader"]["POST"] == 1
                and counts["reader"]["GET"] == 1
            )

            from lax_connector.context_binding_recovery import original_receipt

            pending = {
                "action": "progress",
                "operationId": "progress:unknown",
                "nativeThread": reader.thread,
                "nativeTurn": "original-running-turn",
                "value": {"note": "No execution retry authorized"},
            }
            pending_path = root / "unknown-execution-operation.json"
            old = {"state": "intent", "request": pending}
            saved(pending_path, old)
            before = dict(counts["reader"])
            try:
                await original_receipt(
                    reader, pending, pending["operationId"], pending_path, old
                )
                checks["unknown_nonbind_operation_remains_held_no_POST"] = False
            except HttpFailure as error:
                checks["unknown_nonbind_operation_remains_held_no_POST"] = (
                    error.status == 404
                    and counts["reader"]["POST"] == before["POST"]
                    and json.loads(pending_path.read_text()) == old
                )
            try:
                await http(
                    tokens["reader"],
                    "GET",
                    "agents/" + agent + "/contexts/writer/operations/" + operation,
                )
                checks["other_purpose_receipt_stays403"] = False
            except HttpFailure as error:
                checks["other_purpose_receipt_stays403"] = error.status == 403

            with store.pool.connection() as db:
                accepted = db.execute(
                    "SELECT purpose,operation FROM hb_context_operation WHERE agent=%s ORDER BY purpose",
                    (agent,),
                ).fetchall()
                deliveries = db.execute(
                    "SELECT count(*) AS n FROM hb_delivery WHERE authority=%s",
                    (identity["authorityId"],),
                ).fetchone()["n"]
                permits = db.execute(
                    "SELECT count(*) AS n FROM hb_context_permit WHERE agent=%s",
                    (agent,),
                ).fetchone()["n"]
            checks["two_original_metadata_transactions_zero_work_or_inference"] = (
                len(accepted) == 2 and permits == deliveries == 0
            )
            evidence = {
                "at": time.time(),
                "passed": all(checks.values()),
                "checks": checks,
                "counts": counts,
                "traces": traces,
                "accepted": accepted,
                "scope": __doc__,
                "realLLMCalls": 0,
                "faults": [
                    "Before commit: injected before forwarding original request.",
                    "After commit: actual server response intentionally dropped at SDK boundary.",
                ],
                "noExternalEffectRetryOrExactlyOnceClaim": True,
            }
            saved(root / "result.json", evidence)
            print(
                json.dumps(
                    {
                        "passed": evidence["passed"],
                        "checks": checks,
                        "result": str(root / "result.json"),
                    }
                ),
                flush=True,
            )
            assert evidence["passed"]
    finally:
        await runner.cleanup()
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--database-config", required=True)
    asyncio.run(run(parser.parse_args()))
