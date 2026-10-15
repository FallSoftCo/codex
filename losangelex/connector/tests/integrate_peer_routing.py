"""Native connector tool dispatch through real authenticated Hollywood HTTP; no provider calls."""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

from aiohttp import ClientSession, web
from hollywood_backbone.server import application
from hollywood_backbone.store import Store
from lax_connector.connector import Connector


async def main(spec):
    os.umask(0o077)
    root = Path(spec["evidence"])
    root.mkdir(mode=0o700)
    ids = {
        k: str(uuid4()) for k in ["authority", "room", "host", "peer", "sourceAgent"]
    }
    credentials = {
        k: {"principalId": str(uuid4()), "token": secrets.token_urlsafe(40)}
        for k in ["Owner", "Global"]
    }
    other = {k: secrets.token_urlsafe(40) for k in ["peer", "sourceAgent"]}
    intent = {
        "ids": ids,
        "credentials": credentials,
        "other": other,
        "globalRoomId": ids["room"],
    }
    (root / "intent.json").write_text(json.dumps(intent))
    store = Store(json.loads(Path(spec["databaseConfig"]).read_text()))
    store.bootstrap(ids["authority"], "Peer routing tool qualification", intent)
    owner = credentials["Owner"]["principalId"]
    global_id = credentials["Global"]["principalId"]
    for key, credential in other.items():
        store.principal(owner, ids[key], key, "agent", credential)
        store.membership(
            owner,
            ids["room"],
            ids[key],
            {"can_read": True, "can_post": True, "can_request": True},
            0,
        )
    runner = web.AppRunner(application(store))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 18776).start()
    connector = Connector(
        {
            "state": str(root / "connector"),
            "hollywoodUrl": "http://127.0.0.1:18776",
            "token": other["sourceAgent"],
        }
    )
    checks = []
    try:
        async with ClientSession() as session:
            connector.session = session
            source = store.post(
                owner,
                ids["room"],
                "tool-source",
                {
                    "kind": "request",
                    "body": "Coordinate with a specific independent peer",
                    "audience": "room",
                    "recipientId": ids["sourceAgent"],
                    "sourceEventId": None,
                },
            )
            connector.active = {
                "request": source["event"],
                "delivery": source["deliveries"][0],
            }
            params = {
                "threadId": "peer-routing-fixture",
                "callId": "specific-peer",
                "tool": "hollywood_request",
                "arguments": {
                    "roomId": ids["room"],
                    "recipientId": ids["peer"],
                    "body": "Bounded request for the named peer",
                },
            }
            first = await connector.tool("item/tool/call", params)
            assert first["success"]
            value = json.loads(first["contentItems"][0]["text"])
            assert (
                len(value["deliveries"]) == 1
                and value["deliveries"][0]["agent"] == ids["peer"]
            )
            assert (
                value["event"]["author"] == ids["sourceAgent"]
                and value["event"]["source"] == source["event"]["id"]
            )
            assert value["event"]["data"]["authorKind"] == "agent"
            assert await connector.tool("item/tool/call", params) == first
            altered = await connector.tool(
                "item/tool/call",
                {
                    **params,
                    "arguments": {**params["arguments"], "recipientId": global_id},
                },
            )
            assert not altered["success"]
            checks.append(
                "Explicit same-room peer receives one attributed request; replay is stable and changed recipient on the same native call is held"
            )
            fallback = await connector.tool(
                "item/tool/call",
                {
                    **params,
                    "callId": "default-owner",
                    "arguments": {
                        "roomId": ids["room"],
                        "body": "Explicit request using the default recipient",
                    },
                },
            )
            assert fallback["success"]
            default = json.loads(fallback["contentItems"][0]["text"])
            assert default["deliveries"][0]["agent"] == global_id
            checks.append(
                "Omitted recipient retains the explicit room-default fallback"
            )
            missing = await connector.tool(
                "item/tool/call",
                {
                    **params,
                    "callId": "unauthorized-target",
                    "arguments": {**params["arguments"], "recipientId": str(uuid4())},
                },
            )
            assert not missing["success"]
            private = store.post(
                owner,
                ids["room"],
                "private-source",
                {
                    "kind": "request",
                    "body": "Private human request",
                    "audience": "direct",
                    "recipientId": ids["sourceAgent"],
                    "sourceEventId": None,
                },
            )
            connector.active = {
                "request": private["event"],
                "delivery": private["deliveries"][0],
            }
            denied = await connector.tool(
                "item/tool/call", {**params, "callId": "private-expansion"}
            )
            assert not denied["success"]
            private_journal = connector.state / (
                "tool-"
                + hashlib.sha256(
                    (params["threadId"] + "private-expansion").encode()
                ).hexdigest()
                + ".json"
            )
            assert json.loads(private_journal.read_text())["state"] == "completed"
            checks.append(
                "Unavailable recipient and private-audience expansion reject without a new request"
            )
            with store.pool.connection() as c:
                deliveries = c.execute(
                    "SELECT * FROM hb_delivery WHERE authority=%s", (ids["authority"],)
                ).fetchall()
                assert len(deliveries) == 4
            (root / "result.json").write_text(
                json.dumps(
                    {
                        "passed": True,
                        "checks": checks,
                        "nativeProviderCalls": 0,
                        "transport": "actual authenticated aiohttp + PostgreSQL + LAX tool journal",
                        "productionChanged": False,
                    },
                    indent=2,
                )
            )
            print(json.dumps({"passed": True, "checks": len(checks), "models": 0}))
    finally:
        with store.pool.connection() as c:
            pending = c.execute(
                "SELECT id FROM hb_delivery WHERE authority=%s AND state='pending'",
                (ids["authority"],),
            ).fetchall()
        for d in pending:
            store.cancel(owner, str(d["id"]))
        connector.lock.close()
        await runner.cleanup()
        store.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--spec", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(main(json.loads(args.spec.read_text())))
