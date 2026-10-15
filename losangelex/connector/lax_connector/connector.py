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
import time
from pathlib import Path
from uuid import UUID, uuid4

from aiohttp import ClientSession, ContentTypeError

from .activity import Activity
from .administration import administer
from .attention import APPROVAL, QUESTION, Attention, AttentionExpired
from .errors import HttpFailure
from .journal import saved
from .native_goals import (
    NativeAdmissionUnavailable,
    NativeGoalHeld,
    external_admission,
    bind_role,
    role_scope,
)
from .native_goals import (
    bind as bind_goal,
)
from .native_goals import (
    progress as goal_progress,
)
from .native_goals import restore as restore_goal
from .native_goals import settle as settle_goal
from .roles import RoleContext, validate_administration
from .rpc import AppServer
from .workflow import (
    MUTATION_TOOLS,
    READ_TOOLS,
)
from .workflow import (
    definitions as workflow_definitions,
)
from .workflow import (
    invoke as workflow_tool,
)


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
        "hollywood_room_info",
        "Inspect authorized room ownership, actors and current membership revisions before changing grants. Administrators can see all grants; others see their own.",
        {"roomId": STRING},
        ["roomId"],
    ),
    spec(
        "hollywood_agent_info",
        "Inspect an authorized agent's current primary role, home room and revision before updating its role.",
        {"agentId": STRING},
        ["agentId"],
    ),
    spec(
        "hollywood_publish",
        "Publish communication in this turn's room without requesting anyone to execute.",
        {"body": STRING},
        ["body"],
    ),
    spec(
        "hollywood_request",
        "Address a bounded execution request to a specific authorized peer in a room. Supply recipientId for that peer; omission uses the room default. This starts work, preserves source identity and does not grant the peer new permissions.",
        {"roomId": STRING, "body": STRING, "recipientId": {"type": ["string", "null"]}},
        ["roomId", "body"],
    ),
]
ROLE = {"type": "string", "pattern": "^[a-z][a-z0-9_-]{0,63}$"}
TOOLS += [
    spec(
        "hollywood_ask",
        "Ask the attributable human a necessary scoped question and wait for their authenticated answer. Do not request secrets in chat. Observation alone does not require a question.",
        {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": STRING,
                        "header": STRING,
                        "question": STRING,
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"label": STRING, "description": STRING},
                                "required": ["label", "description"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["id", "header", "question", "options"],
                    "additionalProperties": False,
                },
            }
        },
        ["questions"],
    ),
    spec(
        "lax_provision_worker",
        "Verified Global administrator: provision and start a scoped Linux worker on this enrolled host. Credentials remain private; no model runs until a request is addressed to it.",
        {"agentId": STRING},
        ["agentId"],
    ),
    spec(
        "hollywood_create_agent",
        "Administrator: create a stable scoped agent and primary responsibility. Credential stays protected in LAX. This does not provision execution.",
        {"name": STRING, "primary": ROLE, "purpose": STRING},
        ["name", "primary", "purpose"],
    ),
    spec(
        "hollywood_create_room",
        "Administrator: create a Hollywood room with an accountable agent owner and clear purpose. The owner initially receives read/post/request membership; inspect hollywood_room_info for its current revision before changing grants.",
        {"name": STRING, "purpose": STRING, "ownerId": STRING},
        ["name", "purpose", "ownerId"],
    ),
    spec(
        "hollywood_set_role",
        "Administrator: revise a primary role with revision compare-and-swap; role names do not grant authority.",
        {
            "agentId": STRING,
            "primary": ROLE,
            "purpose": STRING,
            "homeRoomId": {"type": ["string", "null"]},
            "nativeGoalScope": {"type": "string", "enum": ["role", "work"]},
            "revision": {"type": "integer", "minimum": 0},
        },
        ["agentId", "primary", "purpose", "homeRoomId", "revision"],
    ),
    spec(
        "hollywood_grant_room",
        "Administrator: explicitly grant room observation, posting or execution-request rights; none grant host access. First inspect hollywood_room_info for the current membership revision; revision 0 means absent membership.",
        {
            "roomId": STRING,
            "principalId": STRING,
            "can_read": {"type": "boolean"},
            "can_post": {"type": "boolean"},
            "can_request": {"type": "boolean"},
            "revision": {"type": "integer", "minimum": 0},
        },
        ["roomId", "principalId", "can_read", "can_post", "can_request", "revision"],
    ),
]


TOOLS += workflow_definitions(spec)


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
        self.role_context = None
        self.work_briefing = None
        self.goal_binding = None
        self.context_id = None
        self.goal_progress_task = None
        self.goal_progress_closing = False
        self.cancel_requested = False
        self.journal = self.state / "execution.json"
        self.interrupt_task = None
        self.uncertain_tools = False
        self.attention = Attention(self)
        self.native_items = {}
        self.activity = Activity(self)

    async def http(self, method, path, payload=None):
        async with self.session.request(
            method,
            self.config["hollywoodUrl"] + "/hollywood/v3/" + path,
            json=payload,
            headers={"Authorization": "Bearer " + self.config["token"]},
        ) as response:
            try:
                data = await response.json()
            except (ValueError, ContentTypeError) as error:
                if response.status in (400, 403, 409):
                    raise HttpFailure(response.status, "Request rejected") from error
                # A successful write may already have committed. Parsing failure
                # cannot be classified as rejected and invite a replacement effect.
                raise RuntimeError(
                    "Hollywood reply unconfirmed; reconcile the original operation"
                ) from error
            if not isinstance(data, dict):
                raise RuntimeError(
                    "Hollywood reply shape unconfirmed; reconcile the original operation"
                )
            if response.status != 200:
                raise HttpFailure(response.status, data.get("error", "request failed"))
            return data

    async def briefing(self):
        value = await self.http(
            "GET", "connector/deliveries/" + self.active["delivery"]["id"] + "/briefing"
        )
        expected = {
            "schema": "lax-work-briefing/v1",
            "authorityId": self.active["request"]["authority"],
            "agentId": self.config["agentId"],
            "roomId": self.active["request"]["room"],
            "deliveryId": self.active["delivery"]["id"],
            "generation": self.active["delivery"]["generation"],
            "claimId": self.active["delivery"]["claim_id"],
        }
        if any(value.get(k) != v for k, v in expected.items()):
            raise ValueError("Briefing does not match captured execution")
        self.work_briefing = value
        saved(self.state / ("briefing-" + value["deliveryId"] + "-"
                            + str(value["asOfSequence"]) + ".json"), value)
        return value

    async def event(self, method, params):
        if not self.active:
            return
        if (
            method in ("item/started", "item/completed")
            and params.get("threadId") == self.thread
        ):
            item = params.get("item", {})
            if item.get("id"):
                self.native_items[item["id"]] = item
        if method == "turn/started" and params.get("threadId") == self.thread:
            record = json.loads(self.journal.read_text())
            saved(
                self.journal,
                {**record, "nativeTurn": params["turn"]["id"], "state": "running"},
            )
        if (
            method in ("thread/goal/updated", "turn/started")
            and self.goal_binding
            and not self.goal_progress_closing
            and params.get("threadId") == self.thread
        ):
            if not self.goal_progress_task or self.goal_progress_task.done():
                self.goal_progress_task = asyncio.create_task(
                    self.observe_goal_progress()
                )
        self.activity.record(method, params)
        if (
            method == "item/completed"
            and params.get("threadId") == self.thread
            and params.get("item", {}).get("type") == "agentMessage"
        ):
            item = params["item"]
            if item.get("phase") == "final_answer" or not self.final:
                self.final = item.get("text", "")
        elif (
            method == "turn/completed"
            and params.get("threadId") == self.thread
            and self.finished
            and not self.finished.done()
            and params["turn"]["id"]
            == json.loads(self.journal.read_text()).get("nativeTurn")
        ):
            self.finished.set_result(params["turn"])
        elif (
            method == "hollywood/runtimeLost"
            and self.finished
            and not self.finished.done()
        ):
            self.finished.set_exception(
                RuntimeError("Native connection lost; execution must be reconciled")
            )

    async def observe_goal_progress(self):
        try:
            snapshot = await goal_progress(self)
            record = json.loads(self.journal.read_text())
            if record.get("nativeTurn"):
                self.activity.record(
                    "hollywood/goalProgress",
                    {
                        "threadId": self.thread,
                        "turnId": record["nativeTurn"],
                        "goal": snapshot,
                    },
                )
        except Exception as error:
            saved(
                self.state / "goal-observation-gap.json",
                {"error": type(error).__name__, "executionReplayed": False},
            )

    async def tool(self, method, params):
        def output(value, success=True):
            return {
                "success": success,
                "contentItems": [
                    {"type": "inputText", "text": json.dumps(value, default=str)}
                ],
            }

        if not self.active:
            raise RuntimeError("No captured native execution; no approval inferred")
        if method in QUESTION + APPROVAL:
            slot = (
                method + ":" + str(params.get("approvalId") or params["_rpcRequestId"])
            )
            return await self.attention.wait(method, params, slot=slot)
        if method != "item/tool/call":
            raise ValueError("Unsupported native request; no approval inferred")
        call = params["callId"]
        read_only = params["tool"] in READ_TOOLS or params["tool"] in (
            "hollywood_context",
            "hollywood_rooms",
            "hollywood_read_room",
            "hollywood_room_info",
            "hollywood_agent_info",
        )
        if self.uncertain_tools and not read_only:
            return output(
                {
                    "error": "Prior tool effect unconfirmed; further mutations held pending original receipt reconciliation"
                },
                False,
            )
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
        record = {
            "state": "intent",
            "digest": fingerprint,
            "callId": call,
            "tool": params["tool"],
            "requestId": self.active["request"]["id"],
            "nativeThread": params["threadId"],
            "arguments": params["arguments"],
        }
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
                value = self.role_context.value
            elif name == "hollywood_rooms":
                value = await self.http("GET", "rooms")
            elif name == "hollywood_room_info":
                value = await self.http(
                    "GET", "rooms/" + str(UUID(arguments["roomId"]))
                )
            elif name == "hollywood_agent_info":
                value = await self.http(
                    "GET", "agents/" + str(UUID(arguments["agentId"])) + "/role"
                )
            elif name == "hollywood_read_room":
                value = await self.http(
                    "GET",
                    f"rooms/{arguments['roomId']}/history?after={arguments['after']}&limit=10",
                )
            elif name == "hollywood_ask":
                value = await self.attention.wait(
                    "hollywood/question", {**params, **arguments}, slot=call
                )
            elif name in ("hollywood_publish", "hollywood_request"):
                room = arguments.get("roomId", self.active["request"]["room"])
                recipient = arguments.get("recipientId") if name == "hollywood_request" else None
                if (self.active["request"]["audience"] == "direct" and recipient
                        and recipient != self.active["request"]["author"]):
                    raise PermissionError("Private peer delegation requires an explicit sharing contract")
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
                            else {"recipientId": str(UUID(recipient))} if recipient else {}
                        ),
                        "sourceEventId": self.active["request"]["id"],
                    },
                )
                if name == "hollywood_publish":
                    self.publications.append(value["event"]["id"])
            elif name in READ_TOOLS | MUTATION_TOOLS:
                value = await workflow_tool(self, name, arguments, operation)
            elif name in (
                "hollywood_create_agent",
                "hollywood_create_room",
                "hollywood_set_role",
                "hollywood_grant_room",
                "lax_provision_worker",
            ):
                value = await administer(self, name, arguments, operation)
            else:
                raise ValueError("Unknown connector tool")
            result = output(value)
            saved(path, {**record, "state": "completed", "result": result})
            return result
        except Exception as error:
            if (
                read_only
                or isinstance(error, AttentionExpired)
                or isinstance(error, (ValueError, PermissionError))
                or (isinstance(error, HttpFailure) and error.status in (400, 403, 409))
            ):
                result = output(
                    {
                        "error": type(error).__name__,
                        "effect": "rejected",
                        **(
                            {
                                "status": error.status,
                                "message": str(error)[:250],
                                "next": "Inspect the current authorized resource/revision before a corrected command",
                            }
                            if isinstance(error, HttpFailure)
                            else {}
                        ),
                    },
                    False,
                )
                saved(path, {**record, "state": "completed", "result": result})
                return result
            self.uncertain_tools = True
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

    async def transition(self, state, *, operation=None, **details):
        d = self.active["delivery"]
        operation = operation or "lax:" + d["id"] + ":" + state
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

    async def monitor_cancellation(self, turn_id):
        while self.finished and not self.finished.done():
            try:
                receipt = await self.http(
                    "GET", "deliveries/" + self.active["delivery"]["id"]
                )
                if receipt["delivery"]["state"] == "cancel_requested" or receipt[
                    "delivery"
                ].get("cancellation_requested"):
                    self.cancel_requested = True
                    record = json.loads(self.journal.read_text())
                    saved(self.journal, {**record, "cancelRequested": True})
                    params = {"threadId": self.thread, "turnId": turn_id}
                    path = self.state / (
                        "interrupt-" + self.active["delivery"]["id"] + ".json"
                    )
                    saved(path, {"state": "intent", "params": params})
                    reply = await self.rpc.call("turn/interrupt", params)
                    saved(
                        path,
                        {
                            "state": "requested",
                            "params": params,
                            "nativeReceipt": reply,
                            "executionStopped": False,
                            "externalEffectsUndone": False,
                        },
                    )
                    return
            except Exception as error:
                # No model polling or replacement turn. Retain an observation gap
                # while waiting for the same native turn and its terminal event.
                saved(
                    self.state / "cancellation-observation-gap.json",
                    {
                        "error": type(error).__name__,
                        "deliveryId": self.active["delivery"]["id"],
                        "nativeTurn": turn_id,
                    },
                )
            await asyncio.sleep(1)

    async def reconcile(self):
        """Recover the original owner using metadata only; never resume/start a turn."""
        record = json.loads(self.journal.read_text())
        async with ClientSession() as self.session:
            self.active = await self.http(
                "GET", "deliveries/" + record["delivery"]["id"]
            )
            d = self.active["delivery"]
            if (
                d["generation"] != record["delivery"]["generation"]
                or d["claim_id"] != record["delivery"]["claim_id"]
                or d["host"] != self.config["hostId"]
                or d["agent"] != self.config["agentId"]
            ):
                raise RuntimeError(
                    "Native ownership changed; fenced reconciliation required"
                )
            self.thread = record.get("nativeThread")
            if d.get("cancellation_requested") or d["state"] == "cancel_requested":
                record = {**record, "cancelRequested": True}
                saved(self.journal, record)
            terminal = d["state"] in ("completed", "failed", "cancelled")
            if terminal and (
                d["native_turn"] != record.get("nativeTurn")
                or d["native_thread"] != record.get("nativeThread")
            ):
                raise RuntimeError(
                    "Terminal receipt refers to another native execution"
                )
            lifecycle_path = self.state / ("goal-lifecycle-" + d["id"] + ".json")
            lifecycle = (
                json.loads(lifecycle_path.read_text())
                if lifecycle_path.exists()
                else {}
            )
            settled = (
                lifecycle.get("state") == "confirmed"
                and lifecycle.get("intent", {}).get("generation") == d["generation"]
            )
            needs_goal = (
                bool(self.active.get("nativeGoalBinding"))
                and d["state"] in ("cancelled", "failed")
                and not settled
            )
            if terminal and not needs_goal:
                self.activity.start()
                try:
                    await self.activity.flush()
                finally:
                    await self.activity.close()
                saved(
                    self.journal,
                    {
                        **record,
                        "state": d["state"],
                        "reconciled": True,
                        "goalLifecyclePending": False,
                    },
                )
                return {
                    "state": d["state"],
                    "nativeReplay": False,
                    "source": "Hollywood terminal receipt",
                }
            if not record.get("nativeTurn") or not self.thread:
                raise RuntimeError(
                    "Original native turn identity is unconfirmed; no replay"
                )
            self.rpc = AppServer(
                self.config["binary"],
                Path(self.config["codexHome"]),
                self.state / "native",
                self.event,
                self.tool,
                self.attention.submitted,
            )
            self.goal_progress_closing = True
            self.activity.start()
            try:
                await self.rpc.start()
                await external_admission(
                    self.rpc,
                    self.active.get("nativeGoalBinding", {}).get("binding_kind")
                    == "role",
                )
                await restore_goal(self, record)
                if terminal:
                    status, turn = d["state"], None
                else:
                    snapshot = await self.rpc.call(
                        "thread/read", {"threadId": self.thread, "includeTurns": True}
                    )
                    saved(self.state / "native-reconciliation-readback.json", snapshot)
                    turns = [
                        t
                        for t in snapshot["thread"].get("turns", [])
                        if t["id"] == record["nativeTurn"]
                    ]
                    if len(turns) != 1 or turns[0]["status"] == "inProgress":
                        if d["state"] != "unknown":
                            await self.transition("unknown")
                        raise RuntimeError(
                            "Original native turn remains unsettled; no replay"
                        )
                    turn = turns[0]
                    if turn["status"] not in ("completed", "failed", "interrupted"):
                        raise RuntimeError(
                            "Unrecognized original native terminal state"
                        )
                    if any(
                        item.get("type") in ("commandExecution", "dynamicToolCall")
                        and item.get("status")
                        not in ("completed", "failed", "declined")
                        for item in turn.get("items", [])
                    ):
                        if d["state"] != "unknown":
                            await self.transition("unknown")
                        raise RuntimeError(
                            "Native turn has an unresolved tool effect; hold original delivery"
                        )
                    for path in self.state.glob("tool-*.json"):
                        if json.loads(path.read_text())["state"] != "completed":
                            raise RuntimeError(
                                "Unconfirmed Hollywood tool effect; original receipts required"
                            )
                    status = (
                        "completed"
                        if turn["status"] == "completed"
                        else (
                            "cancelled"
                            if turn["status"] == "interrupted"
                            and record.get("cancelRequested")
                            else "failed"
                        )
                    )
                saved(
                    self.journal,
                    {
                        **record,
                        "state": "settling-native-terminal",
                        "observedTerminalState": status,
                        "goalLifecyclePending": needs_goal
                        or status in ("cancelled", "failed"),
                    },
                )
                await settle_goal(self, status)
                if self.goal_binding:
                    native = await goal_progress(self)
                    self.activity.record(
                        "hollywood/goalProgress",
                        {
                            "threadId": self.thread,
                            "turnId": record["nativeTurn"],
                            "goal": native,
                        },
                    )
                await self.activity.flush()
                if not terminal:
                    last = next(
                        (
                            i.get("text", "")
                            for i in reversed(turn.get("items", []))
                            if i.get("type") == "agentMessage" and i.get("text")
                        ),
                        "",
                    )
                    transition_file = self.state / ("transition-" + status + ".json")
                    original = (
                        json.loads(transition_file.read_text())
                        if transition_file.exists()
                        else None
                    )
                    if original and original["deliveryId"] == d["id"]:
                        out = await self.http(
                            "POST",
                            "deliveries/" + d["id"] + "/transition",
                            original["payload"],
                        )
                    else:
                        out = await self.transition(
                            status,
                            nativeThread=self.thread,
                            nativeTurn=record["nativeTurn"],
                            body=last
                            or "Original native terminal state reconciled without replay; inspect linked reports.",
                        )
                else:
                    out = self.active
                saved(
                    self.journal,
                    {
                        **record,
                        "state": status,
                        "reconciled": True,
                        "goalLifecyclePending": False,
                        "receipt": out,
                    },
                )
                return {
                    "state": status,
                    "nativeReplay": False,
                    "source": "Original native ownership and terminal evidence",
                }
            except NativeGoalHeld:
                current = json.loads(self.journal.read_text())
                saved(
                    self.journal,
                    {
                        **current,
                        "state": "goal-reconciliation-required",
                        "goalLifecyclePending": True,
                    },
                )
                raise
            finally:
                await self.activity.close()
                await self.rpc.close()

    async def paced_reconcile(self):
        """Bound resident native metadata reads; persisted uncertainty never creates model work."""
        record = json.loads(self.journal.read_text())
        async with ClientSession() as self.session:
            current = await self.http("GET", "deliveries/" + record["delivery"]["id"])
        d = current["delivery"]
        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    d["id"],
                    d["generation"],
                    d["revision"],
                    d["state"],
                    d.get("cancellation_requested"),
                    record.get("nativeThread"),
                    record.get("nativeTurn"),
                ]
            ).encode()
        ).hexdigest()
        path = self.state / "recovery-observation.json"
        prior = json.loads(path.read_text()) if path.exists() else {}
        unchanged = prior.get("fingerprint") == fingerprint
        attempts = prior.get("attempts", 0) if unchanged else 0
        maximum = max(1, min(8, int(self.config.get("maxUnchangedRecoveryReads", 3))))
        if unchanged and (
            attempts >= maximum or time.time() < prior.get("nextReadAt", 0)
        ):
            saved(
                self.state / "resident-status.json",
                {
                    "state": "held" if attempts >= maximum else "waiting-for-recovery",
                    "deliveryId": d["id"],
                    "nativeMetadataReads": attempts,
                    "manualReconcileRequired": attempts >= maximum,
                    "modelsStartedByObservation": 0,
                },
            )
            return
        delay = min(600, 30 * 2**attempts)
        saved(
            path,
            {
                "fingerprint": fingerprint,
                "attempts": attempts + 1,
                "nextReadAt": time.time() + delay,
                "modelsStarted": 0,
            },
        )
        await self.reconcile()

    async def once(self, claim_operation):
        journal = self.state / "execution.json"
        if journal.exists():
            previous = json.loads(journal.read_text())
            if previous["state"] not in ("completed", "failed", "cancelled"):
                raise RuntimeError(
                    "Unsettled native execution retained; do not replay it"
                )
        self.finished = None
        self.final = ""
        self.publications = []
        self.goal_binding = None
        self.goal_progress_task = None
        self.goal_progress_closing = False
        self.cancel_requested = False
        self.interrupt_task = None
        self.uncertain_tools = False
        async with ClientSession() as self.session:
            policy = await self.http(
                "GET", "agents/" + self.config["agentId"] + "/role"
            )
            principal = await self.http("GET", "principals/" + self.config["agentId"])
            validate_administration(
                policy["primary_role"], principal["administrator"], self.config
            )
            saved(
                self.state / "claim-intent.json",
                {
                    "operationId": claim_operation,
                    "hostId": self.config["hostId"],
                    "capabilities": ["native-role-goals/v1", "cooperation-plan/v1", "work-attempts/v1", "room-briefing/v1"],
                },
            )
            self.active = await self.http(
                "POST",
                "connector/claim",
                {
                    "operationId": claim_operation,
                    "hostId": self.config["hostId"],
                    "capabilities": ["native-role-goals/v1", "cooperation-plan/v1", "work-attempts/v1", "room-briefing/v1"],
                },
            )
            saved(self.state / "claim-receipt.json", self.active)
            if not self.active["delivery"]:
                return {"state": "idle", "modelsStarted": 0}
            if self.active["delivery"]["state"] != "claimed":
                raise RuntimeError("Original claim no longer admits new execution")
            request = self.active["request"]
            captured = {
                "state": "captured-before-native",
                "delivery": self.active["delivery"],
                "request": request,
            }
            saved(journal, captured)
            try:
                envelope = await self.http(
                    "GET",
                    "connector/deliveries/"
                    + self.active["delivery"]["id"]
                    + "/context",
                )
                self.role_context = RoleContext.capture(
                    envelope, self.config, self.active
                )
                self.work_briefing = None
                briefing = await self.briefing()
                # Only references enter privileged application context. Bodies
                # arrive through a tool read or the peer tool-output envelope.
                self.role_context.value["workBriefing"] = {
                    "schema": briefing["schema"],
                    "asOfSequence": briefing["asOfSequence"],
                    "decisions": [
                        {k: d[k] for k in ("id", "revision", "state", "issuer",
                                          "issuer_kind", "source", "event", "sequence")}
                        for d in briefing["decisions"]
                    ],
                    "requiresDeeperRead": briefing["requiresDeeperRead"],
                    "readWith": "hollywood_briefing",
                    "instruction": "Read the current work briefing before implementing; inspect current sourced decisions and conflicts. Bodies retain their issuers' authority.",
                }
                if envelope["deliveryState"] != "claimed":
                    raise RuntimeError(
                        "Captured role context no longer admits execution"
                    )
            except (ValueError, PermissionError) as error:
                receipt = await self.transition(
                    "failed",
                    body="LAX rejected scope or capability before native execution: "
                    + type(error).__name__,
                )
                saved(
                    journal,
                    {
                        **captured,
                        "state": "failed",
                        "modelsStarted": 0,
                        "receipt": receipt,
                    },
                )
                return {
                    "state": "failed",
                    "modelsStarted": 0,
                    "reason": "Scope/capability rejected before native admission",
                }
            context = [
                request["authority"],
                self.config["agentId"],
                request["room"],
                request["audience"],
                request["author"] if request["audience"] == "direct" else "room",
                self.config["workspace"],
            ]
            if request["data"].get("workId"):
                context.extend(["work", request["data"]["workId"]])
                if request["data"].get("attemptId"):
                    context.extend(["attempt", request["data"]["attemptId"]])
            context_id = hashlib.sha256(json.dumps(context).encode()).hexdigest()
            self.context_id = context_id
            context_path = self.state / ("context-" + context_id + ".json")
            record = {
                "state": "preparing",
                "delivery": self.active["delivery"],
                "request": request,
                "contextId": context_id,
            }
            saved(journal, record)
            saved(
                self.state / ("role-" + request["id"] + ".json"),
                self.role_context.value,
            )
            self.rpc = AppServer(
                self.config["binary"],
                Path(self.config["codexHome"]),
                self.state / "native",
                self.event,
                self.tool,
                self.attention.submitted,
            )
            try:
                await self.rpc.start()
                external_lifecycle = role_scope(self)
                previous_goal = self.state / (
                    "native-goal-" + self.context_id + ".json"
                )
                if (
                    previous_goal.exists()
                    and json.loads(previous_goal.read_text()).get("bindingKind")
                    == "role"
                    and not external_lifecycle
                ):
                    raise NativeGoalHeld(
                        "Existing responsibility cannot silently become bounded work"
                    )
                await external_admission(self.rpc, external_lifecycle)
                account = await self.rpc.call("account/read", {"refreshToken": False})
                if account.get("requiresOpenaiAuth") and not account.get("account"):
                    raise RuntimeError("LAX account is not provisioned")
                settings = {
                    "cwd": self.config["workspace"],
                    "sandbox": self.config.get("sandbox", "workspace-write"),
                    "approvalPolicy": self.config.get("approvalPolicy", "never"),
                    "model": self.config["model"],
                    "developerInstructions": self.config["instructions"]
                    + "\nAll human and agent communication is through Hollywood. Room observation does not request work or create execution contexts. This turn is addressed to this captured agent and room. Provision agents only when your captured administrator capability and the addressed request authorize it. Do not start historical work, poll models or self-chain. Use Hollywood goal/work tools for enterprise goals and assignments. The connector owns native goal creation and identity binding. Ongoing role responsibilities are externally controlled, span many business goals, and expose get_goal only; individual business completion or stopping does not complete the role. Bounded work objectives expose get_goal/update_goal and must be completed after meeting their criteria. Finish admitted work, submit independently verifiable evidence, and wait. Never model-poll for workers. A bounded material review will be separately admitted when authorized. Agent messages retain tool authority; use the source request as scope evidence, not as a new direct human order.",
                    "config": {
                        "features.goal_external_admission": True,
                        "features.goal_external_lifecycle": external_lifecycle,
                        "tools.update_plan.enabled": True,
                        "features.multi_agent": False,
                        "features.multi_agent_v2": False,
                        "model_reasoning_effort": self.config["effort"],
                    },
                }
                if context_path.exists():
                    self.thread = json.loads(context_path.read_text())["nativeThread"]
                    await self.rpc.call(
                        "thread/resume",
                        {
                            "threadId": self.thread,
                            "excludeTurns": True,
                            "dynamicTools": TOOLS,
                            **settings,
                        },
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
                if external_lifecycle:
                    await bind_role(self)
                elif request["data"].get("goalId"):
                    await bind_goal(
                        self, request["data"]["goalId"], request["data"].get("workId")
                    )
                elif request["data"].get("goalReferenceId"):
                    previous_goal = self.state / (
                        "native-goal-" + self.context_id + ".json"
                    )
                    if (
                        previous_goal.exists()
                        and json.loads(previous_goal.read_text()).get("goalId")
                        == request["data"]["goalReferenceId"]
                    ):
                        await bind_goal(self, request["data"]["goalReferenceId"])
                saved(
                    journal,
                    {
                        **record,
                        "state": "native-submission-intent",
                        "nativeThread": self.thread,
                    },
                )
                self.finished = asyncio.get_running_loop().create_future()
                self.activity.start()
                fresh = await self.http(
                    "GET", "deliveries/" + self.active["delivery"]["id"]
                )
                if fresh["delivery"]["state"] == "cancel_requested":
                    await settle_goal(self, "cancelled")
                    await self.transition(
                        "cancelled",
                        body="Cancelled before native turn submission; no execution admitted",
                    )
                    saved(
                        journal,
                        {
                            **record,
                            "state": "cancelled",
                            "nativeThread": self.thread,
                            "goalLifecyclePending": False,
                        },
                    )
                    return {"state": "cancelled", "modelsStarted": 0}
                if fresh["delivery"]["state"] != "claimed":
                    raise RuntimeError("Delivery state changed before native admission")
                params = {
                    "threadId": self.thread,
                    "model": self.config["model"],
                    "effort": self.config["effort"],
                    "input": [],
                    "additionalContext": self.role_context.additional_context(),
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
                                "workBriefing": self.work_briefing,
                            }
                        ),
                        "retain": True,
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
                self.interrupt_task = asyncio.create_task(
                    self.monitor_cancellation(turn_id)
                )
                try:
                    await self.transition(
                        "running", nativeThread=self.thread, nativeTurn=turn_id
                    )
                except RuntimeError:
                    current = await self.http(
                        "GET", "deliveries/" + self.active["delivery"]["id"]
                    )
                    receipt = current["delivery"]
                    if (
                        receipt["state"] == "running"
                        and receipt["native_turn"] == turn_id
                        and receipt["native_thread"] == self.thread
                    ):
                        pass  # Original receipt committed before its reply was lost.
                    elif receipt["state"] != "cancel_requested":
                        raise
                    # Cancellation may win between native acceptance and receipt
                    # publication. Interrupt the same owner; never replace it.
                turn = await asyncio.wait_for(
                    self.finished, self.config.get("turnDeadlineSeconds")
                )
                await self.activity.flush()
                if self.uncertain_tools:
                    raise RuntimeError(
                        "Native turn ended with an unconfirmed communication/administration effect; reconcile original tool receipts"
                    )
                status = (
                    "completed"
                    if turn["status"] == "completed"
                    else (
                        "cancelled"
                        if turn["status"] == "interrupted" and self.cancel_requested
                        else "failed"
                    )
                )
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
                current = json.loads(journal.read_text())
                saved(
                    journal,
                    {
                        **current,
                        "state": "native-terminal-observed",
                        "observedTerminalState": status,
                        "goalLifecyclePending": bool(self.goal_binding)
                        and status in ("failed", "cancelled"),
                    },
                )
                if self.goal_binding:
                    self.goal_progress_closing = True
                    if self.goal_progress_task:
                        await asyncio.gather(self.goal_progress_task)
                    await settle_goal(self, status)
                    native = await goal_progress(self)
                    self.activity.record(
                        "hollywood/goalProgress",
                        {"threadId": self.thread, "turnId": turn_id, "goal": native},
                    )
                    if self.goal_progress_task:
                        await asyncio.gather(self.goal_progress_task)
                    await self.activity.flush()
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
            except NativeGoalHeld as error:
                current = json.loads(journal.read_text())
                if current.get("nativeTurn"):
                    saved(
                        journal,
                        {
                            **current,
                            "state": "goal-reconciliation-required",
                            "goalLifecyclePending": True,
                        },
                    )
                    await self.transition("unknown")
                    raise
                receipt = await self.transition(
                    "failed",
                    body="Native goal admission held before model execution: "
                    + str(error),
                )
                saved(
                    journal,
                    {
                        **record,
                        "state": "failed",
                        "modelsStarted": 0,
                        "receipt": receipt,
                    },
                )
                return {"state": "failed", "modelsStarted": 0, "reason": str(error)}
            except NativeAdmissionUnavailable:
                receipt = await self.transition(
                    "failed",
                    body="Native runtime lacks external admission; no context or model turn loaded",
                )
                saved(
                    journal,
                    {
                        **record,
                        "state": "failed",
                        "modelsStarted": 0,
                        "receipt": receipt,
                    },
                )
                return {
                    "state": "failed",
                    "modelsStarted": 0,
                    "reason": "Native admission capability unavailable",
                }
            except Exception:
                try:
                    await self.transition("unknown")
                except Exception:
                    pass
                # Durable native intent is left unsettled for operator/native readback.
                raise
            finally:
                if self.interrupt_task:
                    self.interrupt_task.cancel()
                    await asyncio.gather(self.interrupt_task, return_exceptions=True)
                self.goal_progress_closing = True
                if self.goal_progress_task:
                    await asyncio.gather(
                        self.goal_progress_task, return_exceptions=True
                    )
                await self.activity.close()
                await self.rpc.close()

    async def serve(self):
        """Deterministic queue observer. Idle/unknown states never wake a model."""
        while True:
            try:
                if self.journal.exists():
                    previous = json.loads(self.journal.read_text())
                    if previous["state"] not in (
                        "completed",
                        "failed",
                        "cancelled",
                    ) or previous.get("goalLifecyclePending"):
                        await self.paced_reconcile()
                        await asyncio.sleep(2)
                        continue
                async with ClientSession() as self.session:
                    await self.http(
                        "POST",
                        "connector/reviews",
                        {
                            "hostId": self.config["hostId"],
                            "capabilities": ["native-role-goals/v1", "cooperation-plan/v1", "work-attempts/v1", "room-briefing/v1"],
                        },
                    )
                    projection = await self.http(
                        "GET", "connector/pending?hostId=" + self.config["hostId"]
                    )
                path = self.state / "resident-claim.json"
                if path.exists():
                    intent = json.loads(path.read_text())
                    if self.journal.exists():
                        previous = json.loads(self.journal.read_text())
                        if previous["delivery"]["claim_id"] == intent["operationId"]:
                            async with ClientSession() as self.session:
                                settled = await self.http(
                                    "GET", "deliveries/" + previous["delivery"]["id"]
                                )
                            if settled["delivery"]["state"] not in (
                                "completed",
                                "failed",
                                "cancelled",
                            ):
                                raise RuntimeError(
                                    "Original claim execution remains unsettled"
                                )
                            path.unlink()
                            continue
                    # A reply lost before a local native intent is safe to recover
                    # through the SAME claim identity. once() fences any native intent.
                    result = await self.once(intent["operationId"])
                    saved(self.state / "resident-result.json", result)
                    path.unlink()
                elif (
                    projection["enabled"]
                    and projection["pending"]
                    and not projection["busy"]
                ):
                    if not path.exists():
                        intent = {
                            "pending": projection["pending"]["id"],
                            "operationId": "resident:" + str(uuid4()),
                        }
                        saved(path, intent)
                    result = await self.once(intent["operationId"])
                    saved(self.state / "resident-result.json", result)
                    path.unlink()
                saved(
                    self.state / "resident-status.json",
                    {"state": "waiting", "modelsStartedByObservation": 0},
                )
            except Exception as error:
                saved(
                    self.state / "resident-status.json",
                    {
                        "state": "held",
                        "error": type(error).__name__,
                        "detail": str(error),
                        "modelsStartedByObservation": 0,
                    },
                )
            await asyncio.sleep(2)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--claim-id")
    action.add_argument("--reconcile", action="store_true")
    action.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    connector = Connector(json.loads(args.config.read_text()))
    print(
        json.dumps(
            asyncio.run(
                connector.serve()
                if args.serve
                else connector.reconcile()
                if args.reconcile
                else connector.once(args.claim_id)
            )
        )
    )


if __name__ == "__main__":
    main()
