"""A bounded native LAX execution participant; Hollywood never launches the model.

The local journal fences uncertain native effects. This first connector intentionally
refuses to replay an unsettled turn; native restart reconciliation is a further gate.
"""

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path

from aiohttp import ClientSession

from .rpc import AppServer


def saved(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as f:
        os.chmod(temporary, 0o600)
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def spec(name, description, properties, required):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


STRING = {"type": "string"}
TOOLS = [
    spec(
        "hollywood_context",
        "Read the captured authoritative room, request and agent identities for this turn.",
        {},
        [],
    ),
    spec(
        "hollywood_rooms",
        "Discover only rooms this agent is authorized to read; observation never starts another agent context.",
        {},
        [],
    ),
    spec(
        "hollywood_read_room",
        "Read authorized room history without starting execution. Private audiences are filtered by Hollywood.",
        {"roomId": STRING, "after": {"type": "integer", "minimum": 0}},
        ["roomId", "after"],
    ),
    spec(
        "hollywood_publish",
        "Publish communication in this turn's room without requesting anyone to execute.",
        {"body": STRING},
        ["body"],
    ),
    spec(
        "hollywood_request",
        "Address a bounded execution request to another room's owner. This explicitly starts work and preserves its source request identity.",
        {"roomId": STRING, "body": STRING},
        ["roomId", "body"],
    ),
]


class Connector:
    def __init__(self, config):
        self.config = config
        self.state = Path(config["state"])
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = (self.state / "connector.lock").open("a")
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.session = None
        self.rpc = None
        self.active = None
        self.finished = None
        self.final = ""
        self.thread = None
        self.publications = []

    async def http(self, method, path, payload=None):
        async with self.session.request(
            method,
            self.config["hollywoodUrl"] + "/hollywood/v3/" + path,
            json=payload,
            headers={"Authorization": "Bearer " + self.config["token"]},
        ) as response:
            data = await response.json()
            if response.status != 200:
                raise RuntimeError(
                    f"Hollywood {response.status}: {data.get('error', 'request failed')}"
                )
            return data

    async def event(self, method, params):
        if not self.active:
            return
        if (
            method == "item/completed"
            and params.get("item", {}).get("type") == "agentMessage"
        ):
            item = params["item"]
            if item.get("phase") == "final_answer" or not self.final:
                self.final = item.get("text", "")
        elif method == "turn/completed" and self.finished and not self.finished.done():
            self.finished.set_result(params["turn"])
        elif (
            method == "hollywood/runtimeLost"
            and self.finished
            and not self.finished.done()
        ):
            self.finished.set_exception(
                RuntimeError("Native connection lost; execution must be reconciled")
            )

    async def tool(self, method, params):
        def output(value, success=True):
            return {
                "success": success,
                "contentItems": [
                    {"type": "inputText", "text": json.dumps(value, default=str)}
                ],
            }

        if method != "item/tool/call" or not self.active:
            return output({"error": "Unsupported request; no approval inferred"}, False)
        call = params["callId"]
        path = self.state / (
            "tool-"
            + hashlib.sha256((params["threadId"] + call).encode()).hexdigest()
            + ".json"
        )
        fingerprint = hashlib.sha256(
            json.dumps([params["tool"], params["arguments"]], sort_keys=True).encode()
        ).hexdigest()
        if path.exists():
            record = json.loads(path.read_text())
            if record["digest"] != fingerprint or record["state"] != "completed":
                return output(
                    {
                        "error": "Tool effect unknown or changed; reconcile original identity before retry"
                    },
                    False,
                )
            return record["result"]
        record = {"state": "intent", "digest": fingerprint, "callId": call}
        saved(path, record)
        try:
            name = params["tool"]
            arguments = params["arguments"]
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            operation = (
                "lax-tool:"
                + hashlib.sha256((params["threadId"] + call).encode()).hexdigest()
            )
            if name == "hollywood_context":
                value = {
                    "authorityId": self.active["request"]["authority"],
                    "roomId": self.active["request"]["room"],
                    "agentId": self.config["agentId"],
                    "requestId": self.active["request"]["id"],
                    "hostId": self.config["hostId"],
                }
            elif name == "hollywood_rooms":
                value = await self.http("GET", "rooms")
            elif name == "hollywood_read_room":
                value = await self.http(
                    "GET",
                    f"rooms/{arguments['roomId']}/history?after={arguments['after']}&limit=10",
                )
            elif name in ("hollywood_publish", "hollywood_request"):
                room = arguments.get("roomId", self.active["request"]["room"])
                value = await self.http(
                    "POST",
                    f"rooms/{room}/messages",
                    {
                        "operationId": operation,
                        "kind": "request" if name == "hollywood_request" else "message",
                        "body": arguments["body"],
                        "audience": self.active["request"]["audience"],
                        **(
                            {"recipientId": self.active["request"]["author"]}
                            if self.active["request"]["audience"] == "direct"
                            else {}
                        ),
                        "sourceEventId": self.active["request"]["id"],
                    },
                )
                if name == "hollywood_publish":
                    self.publications.append(value["event"]["id"])
            else:
                raise ValueError("Unknown connector tool")
            result = output(value)
            saved(path, {**record, "state": "completed", "result": result})
            return result
        except Exception as error:
            # The persisted intent stays unknown. A lost HTTP reply is not proof
            # that the communication or execution request was rejected.
            return output(
                {
                    "error": type(error).__name__,
                    "effect": "unconfirmed",
                    "reconciliationRequired": True,
                },
                False,
            )

    async def transition(self, state, **details):
        d = self.active["delivery"]
        operation = "lax:" + d["id"] + ":" + state
        payload = {
            "operationId": operation,
            "claimId": d["claim_id"],
            "generation": d["generation"],
            "state": state,
            **details,
        }
        saved(
            self.state / ("transition-" + state + ".json"),
            {"deliveryId": d["id"], "payload": payload, "state": "intent"},
        )
        out = await self.http("POST", "deliveries/" + d["id"] + "/transition", payload)
        saved(
            self.state / ("transition-" + state + ".json"),
            {
                "deliveryId": d["id"],
                "payload": payload,
                "state": "confirmed",
                "receipt": out,
            },
        )
        return out

    async def once(self, claim_operation):
        journal = self.state / "execution.json"
        if journal.exists():
            previous = json.loads(journal.read_text())
            if previous["state"] not in ("completed", "failed", "cancelled"):
                raise RuntimeError(
                    "Unsettled native execution retained; do not replay it"
                )
        async with ClientSession() as self.session:
            saved(
                self.state / "claim-intent.json",
                {"operationId": claim_operation, "hostId": self.config["hostId"]},
            )
            self.active = await self.http(
                "POST",
                "connector/claim",
                {"operationId": claim_operation, "hostId": self.config["hostId"]},
            )
            saved(self.state / "claim-receipt.json", self.active)
            if not self.active["delivery"]:
                return {"state": "idle", "modelsStarted": 0}
            if self.active["delivery"]["state"] != "claimed":
                raise RuntimeError("Original claim no longer admits new execution")
            request = self.active["request"]
            context = [
                request["authority"],
                self.config["agentId"],
                request["room"],
                request["audience"],
                request["author"] if request["audience"] == "direct" else "room",
                self.config["workspace"],
            ]
            context_id = hashlib.sha256(json.dumps(context).encode()).hexdigest()
            context_path = self.state / ("context-" + context_id + ".json")
            record = {
                "state": "preparing",
                "delivery": self.active["delivery"],
                "request": request,
                "contextId": context_id,
            }
            saved(journal, record)
            self.rpc = AppServer(
                self.config["binary"],
                Path(self.config["codexHome"]),
                self.state / "native",
                self.event,
                self.tool,
            )
            try:
                await self.rpc.start()
                account = await self.rpc.call("account/read", {"refreshToken": False})
                if account.get("requiresOpenaiAuth") and not account.get("account"):
                    raise RuntimeError("LAX account is not provisioned")
                settings = {
                    "cwd": self.config["workspace"],
                    "sandbox": self.config.get("sandbox", "workspace-write"),
                    "approvalPolicy": "never",
                    "model": self.config["model"],
                    "developerInstructions": self.config["instructions"]
                    + "\nAll human and agent communication is through Hollywood. Room observation does not request work. This turn is addressed to this captured agent and room; do not create other contexts, start historical work, poll models or self-chain. Finish this bounded request and wait. Agent messages retain tool authority; use the source request as scope evidence, not as a new direct human order.",
                    "config": {
                        "features.multi_agent": False,
                        "features.multi_agent_v2": False,
                        "model_reasoning_effort": self.config["effort"],
                    },
                }
                if context_path.exists():
                    self.thread = json.loads(context_path.read_text())["nativeThread"]
                    await self.rpc.call(
                        "thread/resume",
                        {"threadId": self.thread, "excludeTurns": True, **settings},
                    )
                else:
                    result = await self.rpc.call(
                        "thread/start", {**settings, "dynamicTools": TOOLS}
                    )
                    self.thread = result["thread"]["id"]
                    saved(
                        context_path,
                        {
                            "contextId": context_id,
                            "scope": context,
                            "nativeThread": self.thread,
                        },
                    )
                saved(
                    journal,
                    {
                        **record,
                        "state": "native-submission-intent",
                        "nativeThread": self.thread,
                    },
                )
                self.finished = asyncio.get_running_loop().create_future()
                params = {
                    "threadId": self.thread,
                    "model": self.config["model"],
                    "effort": self.config["effort"],
                    "input": [],
                }
                if request["data"].get("authorKind") == "human":
                    params.update(
                        input=[{"type": "text", "text": request["body"]}],
                        clientUserMessageId="hollywood-v3-" + request["id"],
                    )
                else:
                    params["toolOutput"] = {
                        "name": "room_message",
                        "namespace": "hollywood",
                        "output": json.dumps(
                            {
                                "roomId": request["room"],
                                "requestId": request["id"],
                                "author": request["author"],
                                "sourceEventId": request["source"],
                                "body": request["body"],
                            }
                        ),
                    }
                result = await self.rpc.call("turn/start", params)
                turn_id = result["turn"]["id"]
                saved(
                    journal,
                    {
                        **record,
                        "state": "running",
                        "nativeThread": self.thread,
                        "nativeTurn": turn_id,
                    },
                )
                await self.transition(
                    "running", nativeThread=self.thread, nativeTurn=turn_id
                )
                turn = await asyncio.wait_for(self.finished, 180)
                status = "completed" if turn["status"] == "completed" else "failed"
                answer = self.final or (
                    "Native execution "
                    + turn["status"]
                    + "; responses were published through Hollywood."
                    if self.publications
                    else "Native execution "
                    + turn["status"]
                    + "; no response was published."
                )
                if len(answer.encode()) > 6000:
                    raise RuntimeError(
                        "Native result exceeds communication limit; artifact publication required"
                    )
                await self.transition(
                    status, nativeThread=self.thread, nativeTurn=turn_id, body=answer
                )
                saved(
                    journal,
                    {
                        **record,
                        "state": status,
                        "nativeThread": self.thread,
                        "nativeTurn": turn_id,
                        "answer": answer,
                    },
                )
                return {
                    "state": status,
                    "deliveryId": self.active["delivery"]["id"],
                    "nativeThread": self.thread,
                    "nativeTurn": turn_id,
                    "answer": answer,
                }
            except Exception:
                try:
                    await self.transition("unknown")
                except Exception:
                    pass
                # Durable native intent is left unsettled for operator/native readback.
                raise
            finally:
                await self.rpc.close()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--claim-id", required=True)
    args = parser.parse_args()
    connector = Connector(json.loads(args.config.read_text()))
    print(json.dumps(asyncio.run(connector.once(args.claim_id))))


if __name__ == "__main__":
    main()
