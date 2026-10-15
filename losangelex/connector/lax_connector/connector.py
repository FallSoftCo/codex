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
import tempfile
from pathlib import Path
from uuid import uuid4

from aiohttp import ClientSession, ContentTypeError

from .activity import Activity
from .administration import administer
from .attention import APPROVAL, QUESTION, Attention, AttentionExpired
from .native_goals import (
    NativeAdmissionUnavailable,
    NativeGoalHeld,
    external_admission,
)
from .native_goals import (
    bind as bind_goal,
)
from .native_goals import (
    progress as goal_progress,
)
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


def saved(path, value):
    descriptor, filename = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(filename)
    with os.fdopen(descriptor, "w") as f:
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
        "Administrator: create a Hollywood room with an accountable agent owner and clear purpose.",
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
            "revision": {"type": "integer", "minimum": 0},
        },
        ["agentId", "primary", "purpose", "homeRoomId", "revision"],
    ),
    spec(
        "hollywood_grant_room",
        "Administrator: explicitly grant room observation, posting or execution-request rights; none of these grant host access.",
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


class HttpFailure(RuntimeError):
    def __init__(self, status, message):
        super().__init__(f"Hollywood {status}: {message}")
        self.status = status


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
                    {"error": type(error).__name__, "effect": "rejected"}, False
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
                if receipt["delivery"]["state"] == "cancel_requested":
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
        """Read the original native owner and reconcile metadata; never start a turn."""
        record = json.loads(self.journal.read_text())
        if record["state"] in ("completed", "failed", "cancelled"):
            return {"state": record["state"], "nativeReplay": False}
        async with ClientSession() as self.session:
            self.active = await self.http(
                "GET", "deliveries/" + record["delivery"]["id"]
            )
            self.thread = record.get("nativeThread")
            d = self.active["delivery"]
            if (
                d["generation"] != record["delivery"]["generation"]
                or d["host"] != self.config["hostId"]
            ):
                raise RuntimeError(
                    "Native ownership changed; fenced reconciliation required"
                )
            if d["state"] in ("completed", "failed", "cancelled"):
                self.activity.start()
                await self.activity.flush()
                await self.activity.close()
                if d["native_turn"] != record.get("nativeTurn") or d[
                    "native_thread"
                ] != record.get("nativeThread"):
                    raise RuntimeError("Terminal receipt refers to another native turn")
                if d["state"] == "completed" and not record.get("nativeTurn"):
                    raise RuntimeError(
                        "Cannot establish native completion without original native ownership"
                    )
                saved(self.journal, {**record, "state": d["state"], "reconciled": True})
                return {
                    "state": d["state"],
                    "nativeReplay": False,
                    "source": "Hollywood terminal receipt",
                }
            if not record.get("nativeTurn") or not record.get("nativeThread"):
                raise RuntimeError(
                    "Native submission outcome lacks an authoritative turn ID; original effect remains unknown"
                )
            self.rpc = AppServer(
                self.config["binary"],
                Path(self.config["codexHome"]),
                self.state / "native",
                self.event,
                self.tool,
                self.attention.submitted,
            )
            self.activity.start()
            try:
                await self.rpc.start()
                snapshot = await self.rpc.call(
                    "thread/read", {"threadId": self.thread, "includeTurns": True}
                )
                turns = [
                    t
                    for t in snapshot["thread"].get("turns", [])
                    if t["id"] == record["nativeTurn"]
                ]
                saved(self.state / "native-reconciliation-readback.json", snapshot)
                if len(turns) != 1 or turns[0]["status"] == "inProgress":
                    raise RuntimeError(
                        "Original native turn remains unsettled; no replay"
                    )
                turn = turns[0]
                for item in turn.get("items", []):
                    if item.get("type") in (
                        "commandExecution",
                        "dynamicToolCall",
                    ) and item.get("status") not in ("completed", "failed", "declined"):
                        raise RuntimeError(
                            "Native turn has an unresolved tool effect; hold original delivery"
                        )
                pending_tools = []
                for path in self.state.glob("tool-*.json"):
                    item = json.loads(path.read_text())
                    if item["state"] != "completed":
                        pending_tools.append(path.name)
                if pending_tools:
                    raise RuntimeError(
                        "Unconfirmed Hollywood tool effects must be reconciled first"
                    )
                await self.activity.flush()
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
                last = next(
                    (
                        item.get("text", "")
                        for item in reversed(turn.get("items", []))
                        if item.get("type") == "agentMessage" and item.get("text")
                    ),
                    "",
                )
                transition_file = self.state / ("transition-" + status + ".json")
                if transition_file.exists():
                    original = json.loads(transition_file.read_text())
                    if original["deliveryId"] == d["id"]:
                        out = await self.http(
                            "POST",
                            "deliveries/" + d["id"] + "/transition",
                            original["payload"],
                        )
                    else:
                        out = await self.transition(
                            status,
                            nativeThread=self.thread,
                            nativeTurn=turn["id"],
                            body=last
                            or "Native terminal state reconciled without replay; inspect linked room reports.",
                        )
                else:
                    out = await self.transition(
                        status,
                        nativeThread=self.thread,
                        nativeTurn=turn["id"],
                        body=last
                        or "Native terminal state reconciled without replay; inspect linked room reports.",
                    )
                saved(
                    self.journal,
                    {**record, "state": status, "reconciled": True, "receipt": out},
                )
                return {
                    "state": status,
                    "nativeReplay": False,
                    "source": "Native persisted terminal turn",
                }
            finally:
                await self.activity.close()
                await self.rpc.close()

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
                await external_admission(self.rpc)
                account = await self.rpc.call("account/read", {"refreshToken": False})
                if account.get("requiresOpenaiAuth") and not account.get("account"):
                    raise RuntimeError("LAX account is not provisioned")
                settings = {
                    "cwd": self.config["workspace"],
                    "sandbox": self.config.get("sandbox", "workspace-write"),
                    "approvalPolicy": self.config.get("approvalPolicy", "never"),
                    "model": self.config["model"],
                    "developerInstructions": self.config["instructions"]
                    + "\nAll human and agent communication is through Hollywood. Room observation does not request work or create execution contexts. This turn is addressed to this captured agent and room. Provision agents only when your captured administrator capability and the addressed request authorize it. Do not start historical work, poll models or self-chain. Use Hollywood goal/work tools for enterprise goals and assignments. The connector owns native goal creation and identity binding; use native get_goal/update_goal for the current execution objective. Finish admitted work, submit independently verifiable evidence, and wait. Never model-poll for workers. A bounded material review will be separately admitted when authorized. Agent messages retain tool authority; use the source request as scope evidence, not as a new direct human order.",
                    "config": {
                        "features.goal_external_admission": True,
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
                if request["data"].get("goalId"):
                    await bind_goal(
                        self, request["data"]["goalId"], request["data"].get("workId")
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
                self.activity.start()
                fresh = await self.http(
                    "GET", "deliveries/" + self.active["delivery"]["id"]
                )
                if fresh["delivery"]["state"] == "cancel_requested":
                    await self.transition(
                        "cancelled",
                        body="Cancelled before native turn submission; no execution admitted",
                    )
                    saved(journal, {**record, "state": "cancelled"})
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
                if self.goal_binding:
                    self.goal_progress_closing = True
                    if self.goal_progress_task:
                        await asyncio.gather(self.goal_progress_task)
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
                    if previous["state"] not in ("completed", "failed", "cancelled"):
                        await self.reconcile()
                        await asyncio.sleep(2)
                        continue
                async with ClientSession() as self.session:
                    await self.http(
                        "POST", "connector/reviews", {"hostId": self.config["hostId"]}
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
