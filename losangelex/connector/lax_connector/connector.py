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
from .agent_context import AgentContext
from .passive_context import PassiveReceiver
from .passive_readback import RolloutReadback
from .continuation_context import LocatorLedger, prepare_context, index_accepted_delegation
from .participation import INSTRUCTIONS as PARTICIPATION, history_path, initialization, message
from .administration import administer
from .attention import APPROVAL, QUESTION, Attention, AttentionExpired
from .errors import HttpFailure, ToolValidationError
from .execution_lifecycle import ExecutionLifecycle
from .effects import Effects
from .journal import ExecutionJournals, saved
from .native_controls import NativeControls
from .native_policy import NativeToolPolicyUnavailable
from .native_policy import normalized as normalize_tool_policy
from .native_policy import verify as verify_tool_policy
from .native_goals import (
    NativeAdmissionUnavailable,
    NativeGoalHeld,
    external_admission,
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


CAPABILITIES = ['persistent-agent-context/v1', 'native-role-goals/v1', 'cooperation-plan/v1', 'work-attempts/v1', 'room-briefing/v1', 'host-admission/v1', 'portfolio-supervision/v1', 'native-human-controls/v1', 'attempt-journals/v1', 'native-executor-launch/v1', 'native-effect-source/v1']
CAPABILITIES += ['completed-work-report-reconciliation/v1', 'completed-report-scope/v1']

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
        "Read authorized room conversation (default), execution activity, or both without starting execution. Latest by default. Cursors belong to this room/view; private audiences are filtered by Hollywood.",
        {"roomId": STRING, "after": {"type":"integer","minimum":0},
         "before":{"type":"integer","minimum":1},"limit":{"type":"integer","minimum":1,"maximum":100},
         "view":{"type":"string","enum":["conversation","activity","all"]}},
        ["roomId"],
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
        {"body":STRING,"roomId":STRING,"recipientId":{"type":["string","null"]},
         "audience":{"type":"string","enum":["room","direct"]},"sourceEventId":STRING},
        ["body"],
    ),
    spec(
        "hollywood_request",
        "Address a bounded execution request to a specific authorized peer in a room. Supply recipientId for that peer; omission uses the room default. This starts work, preserves source identity and does not grant the peer new permissions.",
        {"roomId": STRING, "body": STRING, "recipientId": {"type": ["string", "null"]},
         "audience":{"type":"string","enum":["room","direct"]},"sourceEventId":STRING},
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
        {"agentId": STRING, "serviceMemoryMaxBytes": {"type":"integer", "minimum":268435456, "maximum":1099511627776}},
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


TOOLS.append(spec(
    "hollywood_grant_resource",
    "Administrator: revise canonical access to an already registered physical resource for an enrolled placed agent. Inspect current resource/grant revisions first; absent grants deny access. Metadata grants do not change Unix permissions, admit a turn, or start a service.",
    {"workspaceId": STRING, "agentId": STRING, "executionHost": STRING,
     "revision": {"type": "integer", "minimum": 0},
     "workspaceRevision": {"type": "integer", "minimum": 1},
     "state": {"type": "string", "enum": ["active", "revoked"]},
     "canRead": {"type": "boolean"}, "canWrite": {"type": "boolean"}},
    ["workspaceId", "agentId", "executionHost", "revision", "workspaceRevision", "state", "canRead", "canWrite"],
))


TOOLS += workflow_definitions(spec)
from .mutation_tools import definitions as mutation_definitions
TOOLS += mutation_definitions(spec)


class Connector:
    def __init__(self, config):
        self.config = config
        self.required_tool_policy = config.get("nativeToolPolicy")
        if self.required_tool_policy is not None:
            normalize_tool_policy(self.required_tool_policy)
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
        self.causal_task_context = None
        self.passive_receiver = None
        self.passive_epoch = None
        self.passive_readback = None
        self.work_briefings = {}
        self.report_scope_reads = {}
        self.report_scope_briefings = {}
        self.goal_binding = None
        self.agent_binding = None
        self.agent_context = AgentContext(self)
        self.context_id = None
        self.goal_progress_task = None
        self.goal_progress_closing = False
        self.cancel_requested = False
        self.executions = ExecutionJournals(
            self.state, agent=config["agentId"], host=config["hostId"]
        )
        self.journal = self.executions.current()
        self.interrupt_task = None
        self.control_task = None
        self.uncertain_tools = False
        self.attention = Attention(self)
        self.native_items = {}
        self.executor = None
        self.activity = Activity(self)
        self.effects = Effects(self)
        self.controls = NativeControls(self)
        self.tool_admission = asyncio.Event()

    async def http(self, method, path, payload=None):
        marker = self.effects.before(method, path, payload)
        try:
            result = await self._http(method, path, payload)
        except Exception as error:
            self.effects.after(marker, error=error)
            try:
                recovered = await self.effects.recover_http(marker)
            except Exception:
                recovered = None
            if recovered is not None:
                return recovered
            raise
        self.effects.after(marker, result=result)
        return result

    def native_child_admission_available(self):
        from .collaboration_bridge import IMPLEMENTED_PORTS
        return "native-child-admission" in IMPLEMENTED_PORTS

    async def _http(self, method, path, payload=None):
        headers = {"Authorization": "Bearer " + self.config["token"]}
        context = self.effects.current.get()
        if context and method in ("POST", "PUT", "PATCH", "DELETE"):
            scope = context["scope"]
            fields = (
                "authorityId", "agentId", "hostId", "deliveryId", "claimId",
                "generation", "requestId", "nativeThread", "nativeTurn",
                "callId", "tool", "argumentsDigest", "roleRevision",
                "contextId", "nativeGoalId",
            )
            headers["X-Hollywood-Native-Source"] = json.dumps(
                {"schema": "hollywood-native-source/v2" if self.agent_binding else "hollywood-native-source/v1",
                 **{key: scope[key] for key in fields}},
                separators=(",", ":"),
            )
        async with self.session.request(
            method,
            self.config["hollywoodUrl"] + "/hollywood/v3/" + path,
            json=payload,
            headers=headers,
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

    async def briefing(self, delivery_id=None):
        # An explicit original-delivery read preserves current execution identity.
        if not self.active:
            raise PermissionError("Briefing requires current participation")
        target = str(UUID(delivery_id)) if delivery_id else self.active["delivery"]["id"]
        captured = self.active if target == self.active["delivery"]["id"] else await self.http("GET", "deliveries/" + target)
        delivery, request = captured["delivery"], captured["request"]
        if delivery["agent"] != self.config["agentId"] or request["authority"] != self.active["request"]["authority"]:
            raise PermissionError("Original briefing belongs to a different participant")
        value = await self.http("GET", "connector/deliveries/" + target + "/briefing")
        expected = {
            "schema": "lax-work-briefing/v1", "authorityId": request["authority"],
            "agentId": self.config["agentId"], "roomId": request["room"],
            "deliveryId": target, "generation": delivery["generation"], "claimId": delivery["claim_id"],
        }
        if any(value.get(k) != v for k, v in expected.items()):
            raise ValueError("Briefing does not match exact original execution scope")
        self.work_briefings[target] = value
        if target == self.active["delivery"]["id"]:
            self.work_briefing = value
        saved(self.state / ("briefing-" + target + "-" + str(value["asOfSequence"]) + ".json"), value)
        if target == self.active["delivery"]["id"] and getattr(self, "owner_briefing_delivery", None) == target:
            from .owner_briefing import publish
            await publish(self, value)
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
        # The native reader must keep receiving turn/start's reply while an early
        # callback waits. No dynamic tool or question may race the authoritative
        # running receipt. Failed/cancelled submission closes these waiting tasks.
        await self.tool_admission.wait()
        if params.get("threadId", self.thread) != self.thread:
            raise RuntimeError("Native callback context changed")
        with self.effects.tool_scope(method, params):
            return await self._tool(method, params)

    async def _tool(self, method, params):
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
        control = params["tool"] in ("hollywood_execution_cancel", "hollywood_work_cancel")
        if params["tool"] == "hollywood_goal_state":
            try:
                control = (json.loads(params["arguments"]) if isinstance(params["arguments"], str) else params["arguments"]).get("state") == "cancelled"
            except (ValueError, TypeError, AttributeError):
                control = False
        if self.uncertain_tools and not (read_only or control):
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
                value = initialization(self)
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
                value = await self.http("GET", history_path(arguments))
                if value.get("view") != arguments.get("view", "conversation"):
                    raise ValueError("Hollywood room projection is unavailable; reconcile server version")
            elif name == "hollywood_ask":
                value = await self.attention.wait(
                    "hollywood/question", {**params, **arguments}, slot=call
                )
            elif name in ("hollywood_publish", "hollywood_request"):
                room, payload = message(self, name, arguments, operation)
                value = await self.http("POST", f"rooms/{room}/messages", payload)
                if name == "hollywood_request":
                    value = await index_accepted_delegation(
                        lambda path: self.http("GET", path),
                        LocatorLedger(self.state / "causal-locators-v2"),
                        self.active, value,
                    )
                if name == "hollywood_publish":
                    self.publications.append(value["event"]["id"])
            elif name == "hollywood_mutation_read":
                from .mutation_tools import view as mutation_view
                value = mutation_view(await self.http(
                    "GET", "collaboration/delivery-edits/" + str(UUID(arguments["permitId"]))))
            elif name in READ_TOOLS | MUTATION_TOOLS:
                value = await workflow_tool(self, name, arguments, operation)
            elif name in (
                "hollywood_create_agent",
                "hollywood_create_room",
                "hollywood_set_role",
                "hollywood_grant_room",
                "hollywood_grant_resource",
                "hollywood_select_resource_default",
                "hollywood_placement_set",
                "hollywood_mutation_observe",
                "hollywood_mutation_reconcile",
                "lax_provision_worker",
            ):
                value = await administer(self, name, arguments, operation)
            else:
                raise ValueError("Unknown connector tool")
            result = output(value)
            saved(path, {**record, "state": "completed", "result": result})
            return result
        except Exception as error:
            if not read_only and not isinstance(error, AttentionExpired):
                try:
                    recovered = await self.effects.recover_live()
                except Exception:
                    recovered = None  # Original uncertainty remains fenced.
                if recovered is not None:
                    if params["tool"] == "hollywood_request":
                        recovered = await index_accepted_delegation(
                            lambda path: self.http("GET", path),
                            LocatorLedger(self.state / "causal-locators-v2"),
                            self.active, recovered,
                        )
                    if params["tool"] == "hollywood_publish":
                        event_id = recovered["event"]["id"]
                        if event_id not in self.publications:
                            self.publications.append(event_id)
                    result = output(recovered)
                    saved(path, {**record, "state": "completed", "result": result, "effectRecoveredByOriginalRead": True})
                    return result
            if (
                read_only
                or isinstance(error, AttentionExpired)
                or self.effects.safe_rejection() and (
                    isinstance(error, (ValueError, PermissionError))
                    or isinstance(error, HttpFailure) and error.status in (400, 403, 409)
                )
            ):
                result = output(
                    {
                        "error": type(error).__name__,
                        "effect": "rejected",
                        **(error.public_details() if isinstance(error, ToolValidationError) else {}),
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

    def transition_path(self, state):
        path = self.journal.directory / ("transition-" + state + ".json")
        previous = self.state / path.name
        if not path.exists() and previous.exists():
            receipt = json.loads(previous.read_text())
            delivery = self.active["delivery"]
            payload = receipt.get("payload", {})
            if (
                receipt.get("deliveryId") == delivery["id"]
                and payload.get("generation") == delivery["generation"]
                and payload.get("claimId") == delivery["claim_id"]
            ):
                saved(path, receipt)
        return path

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
            self.transition_path(state),
            {"deliveryId": d["id"], "payload": payload, "state": "intent"},
        )
        out = await self.http("POST", "deliveries/" + d["id"] + "/transition", payload)
        saved(
            self.transition_path(state),
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

    async def receive_passive_context(self):
        # Existing connection/pump owns native calls; never read its socket here.
        if (self.passive_receiver is None or not self.rpc or not self.rpc.process
                or self.rpc.process.returncode is not None):
            return
        try:
            if self.passive_readback is None:
                provider = RolloutReadback(
                    self.state / ("passive-native-" + self.context_id),
                    binding=self.passive_receiver.binding,
                    codex_home=self.config["codexHome"],
                    registered_host_id=self.config["hostId"],
                )
                provider.check_capture(self.active)
                # Metadata locates this exact local store. It is not raw-item proof.
                reply = self.passive_native_started
                if not self.passive_new_thread:
                    reply = await self.rpc.call("thread/read", {
                        "threadId": self.thread, "includeTurns": False,
                    }, timeout=5)
                provider.bind_native(reply, fresh=self.passive_new_thread)
                self.passive_readback = provider
            await asyncio.wait_for(self.passive_receiver.tick(
                lambda path: self.http("GET", path),
                lambda method, params: self.rpc.call(method, params, timeout=5),
                captured=self.active,
                loaded=bool(self.rpc and self.rpc.process and self.rpc.process.returncode is None),
                connection_epoch=self.passive_epoch,
                readback=self.passive_readback,
            ), timeout=5)
        except Exception as error:
            saved(self.state / "passive-context-gap.json", {
                "error": type(error).__name__, "executionAdmitted": False,
                "nativeReplayAllowed": False,
            })

    async def monitor_guidance(self, turn_id):
        # Guidance transport must not serialize or delay the independent Stop lane.
        while self.finished and not self.finished.done():
            try:
                await self.controls.tick(turn_id)
                # Serial with guidance on its existing pump, same AppServer.call
                # and sole _read task. Stop retains its independent lane.
                await self.receive_passive_context()
            except Exception as error:
                saved(self.state / "guidance-observation-gap.json", {
                    "error": type(error).__name__, "deliveryId": self.active["delivery"]["id"],
                    "nativeTurn": turn_id, "executionReplayed": False,
                })
            await asyncio.sleep(1)

    async def read_guidance(self, rows, turn_id):
        """Open only the captured native store; do not load a context or admit input."""
        async def event(*args):
            pass

        async def request(*args):
            raise RuntimeError("Guidance readback cannot execute native requests")

        previous_rpc = self.rpc
        self.rpc = AppServer(
            self.config["binary"], Path(self.config["codexHome"]), self.state / "native",
            event, request,
        )
        try:
            await self.rpc.start()
            await external_admission(
                self.rpc, self.active.get("nativeGoalBinding", {}).get("binding_kind") == "role"
            )
            snapshot = await self.rpc.call(
                "thread/read", {"threadId": self.thread, "includeTurns": True}
            )
            turns = [t for t in snapshot["thread"].get("turns", []) if t["id"] == turn_id]
            if len(turns) != 1:
                raise RuntimeError("Original native turn unavailable; guidance remains held")
            saved(self.state / ("guidance-read-" + self.active["delivery"]["id"] + ".json"),
                  {"nativeThread": self.thread, "turn": turns[0]})
            return await self.controls.reconcile_rows(rows, turns[0])
        finally:
            await self.rpc.close()
            self.rpc = previous_rpc

    async def reconcile_guidance(self, identity):
        """Reconcile one original control without overwriting a later execution journal."""
        identity = str(UUID(identity))
        async with ClientSession() as self.session:
            row = await self.http("GET", "native-controls/" + identity)
            self.active = await self.http("GET", "deliveries/" + row["scope"]["deliveryId"])
            d = self.active["delivery"]
            self.thread = row["scope"]["nativeThread"]
            if (
                d["native_thread"] != self.thread or d["native_turn"] != row["scope"]["nativeTurn"]
                or row["control"]["id"] != identity
            ):
                raise RuntimeError("Original guidance native owner changed")
            self.controls.matches(row, row["scope"]["nativeTurn"])
            if row["control"]["state"] in ("native_recorded", "rejected"):
                results = await self.controls.reconcile_rows([row])
            else:
                results = await self.read_guidance([row], row["scope"]["nativeTurn"])
            return {"guidance": results, "nativeReplay": False, "latestExecutionJournalChanged": False}

    async def reconcile_attempt(self, delivery_id, generation):
        """Inspect one captured original attempt without replacing the latest."""
        if self.rpc and self.rpc.process and self.rpc.process.returncode is None:
            raise RuntimeError("Old-attempt recovery cannot replace a live native transport")
        fields = (
            "journal", "active", "thread", "rpc", "goal_binding", "agent_binding",
            "context_id", "goal_progress_closing",
        )
        previous = {name: getattr(self, name) for name in fields}
        self.journal = self.executions.open(delivery_id, generation)
        try:
            return await self.reconcile()
        finally:
            for name, value in previous.items():
                setattr(self, name, value)

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
            guidance = []
            if record.get("nativeTurn") and self.thread:
                open_controls = await self.controls.pending(record["nativeTurn"])
                if terminal and open_controls:
                    guidance = await self.read_guidance(open_controls, record["nativeTurn"])
            else:
                open_controls = []
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
                    "guidance": guidance,
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
                    saved(self.journal.directory / "native-reconciliation-readback.json", snapshot)
                    turns = [
                        t
                        for t in snapshot["thread"].get("turns", [])
                        if t["id"] == record["nativeTurn"]
                    ]
                    if len(turns) == 1 and open_controls:
                        guidance = await self.controls.reconcile_rows(open_controls, turns[0])
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
                    from .recovery import reconcile_failed_questions

                    try:
                        await reconcile_failed_questions(self, record, turn)
                        await self.effects.reconcile(record, turn)
                    except Exception:
                        if d["state"] != "unknown":
                            await self.transition("unknown")
                        raise
                    if any(
                        item.get("status") is not None
                        and item["status"] not in ("completed", "failed", "declined")
                        for item in turn.get("items", [])
                    ):
                        if d["state"] != "unknown":
                            await self.transition("unknown")
                        raise RuntimeError(
                            "Native turn has an unresolved tool effect; hold original delivery"
                        )
                    for path in self.state.glob("tool-*.json"):
                        original_tool = json.loads(path.read_text())
                        if (
                            original_tool.get("requestId") != self.active["request"]["id"]
                            or original_tool.get("nativeThread") != record["nativeThread"]
                        ):
                            continue
                        if original_tool["state"] != "completed":
                            if d["state"] != "unknown":
                                await self.transition("unknown")
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
                    transition_file = self.transition_path(status)
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
                    "guidance": guidance,
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
        path = self.journal.directory / "recovery-observation.json"
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
        if self.executions.unsettled():
            raise RuntimeError(
                "Unsettled native execution retained; do not replay it"
            )
        self.finished = None
        self.tool_admission.clear()
        self.final = ""
        self.publications = []
        self.native_items = {}
        self.executor = None
        self.goal_binding = None
        self.agent_binding = None
        self.owner_briefing_delivery = None
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
                    "capabilities": CAPABILITIES,
                },
            )
            self.active = await self.http(
                "POST",
                "connector/claim",
                {
                    "operationId": claim_operation,
                    "hostId": self.config["hostId"],
                    "capabilities": CAPABILITIES,
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
            self.journal = self.executions.begin(captured)
            journal = self.journal
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
                        {
                            k: d[k]
                            for k in (
                                "id",
                                "revision",
                                "state",
                                "issuer",
                                "issuer_kind",
                                "source",
                                "event",
                                "sequence",
                            )
                        }
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
                self.causal_task_context = await prepare_context(
                    lambda path: self.http("GET", path), self.state, self.active,
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
            context_id, context_path = self.agent_context.select()
            context = [request["authority"], self.config["agentId"]]
            self.context_id = context_id
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
            self.executor = ExecutionLifecycle(self)
            self.rpc = AppServer(
                self.config["binary"],
                Path(self.config["codexHome"]),
                self.state / "native",
                self.event,
                self.tool,
                self.attention.submitted,
                on_spawn=self.executor.attach,
                enterprise=True,
                collaboration_channel=self.config.get("nativeCollaborationChannel") or (
                    str(Path("/etc/harness") / request["authority"] / "collaboration" /
                        self.config["hostId"] / "channel.json")
                    if (Path("/etc/harness") / request["authority"] / "collaboration" /
                        self.config["hostId"] / "channel.json").is_file() else None
                ),
            )
            try:
                await self.executor.prepare()
                record = {**record, "executorId": self.executor.id}
                saved(journal, record)
                await self.rpc.start()
                external_lifecycle = False
                await external_admission(self.rpc, external_lifecycle)
                account = await self.rpc.call("account/read", {"refreshToken": False})
                if account.get("requiresOpenaiAuth") and not account.get("account"):
                    raise RuntimeError("LAX account is not provisioned")
                settings = {
                    "cwd": self.config["workspace"],
                    "sandbox": self.config.get("sandbox", "danger-full-access"),
                    "approvalPolicy": self.config.get("approvalPolicy", "never"),
                    "model": self.config["model"],
                    "developerInstructions": self.config["instructions"] + PARTICIPATION,
                    "config": {
                        "features.goal_external_admission": True,
                        "features.goal_external_lifecycle": external_lifecycle,
                        "tools.update_plan.enabled": True,
                        # No local/hidden child fallback: native shared children require a real admitted port.
                        "features.multi_agent": self.native_child_admission_available(),
                        "features.multi_agent_v2": self.native_child_admission_available(),
                        "model_reasoning_effort": self.config["effort"],
                    },
                }
                if self.required_tool_policy is not None:
                    settings["toolPolicy"] = self.required_tool_policy
                self.passive_new_thread = not context_path.exists()
                if context_path.exists():
                    self.thread = json.loads(context_path.read_text())["nativeThread"]
                    native_started = await self.rpc.call(
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
                    native_started = result
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
                        "state": "verifying-native-tool-policy",
                        "nativeThread": self.thread,
                        "requestedNativeToolPolicy": self.required_tool_policy,
                    },
                )
                effective_policy = verify_tool_policy(
                    self.required_tool_policy, native_started
                )
                self.role_context.value["nativeToolPolicy"] = effective_policy
                saved(
                    self.state / ("native-policy-" + request["id"] + ".json"),
                    {
                        "requested": self.required_tool_policy,
                        "effective": effective_policy,
                        "nativeThread": self.thread,
                        "modelsStartedByVerification": 0,
                    },
                )
                await self.agent_context.bind()
                self.owner_briefing_delivery = self.active["delivery"]["id"]
                from .owner_briefing import publish as publish_owner_briefing
                await publish_owner_briefing(self, self.work_briefing)
                # Thread was normally loaded above; observation never starts it.
                self.passive_receiver = None
                self.passive_readback = None
                self.passive_native_started = native_started
                self.passive_epoch = self.active["delivery"]["id"] + ":" + str(self.rpc.process.pid)
                try:
                    self.passive_receiver = PassiveReceiver(
                        self.state / ("passive-" + self.context_id),
                        authority_id=request["authority"], principal_id=self.config["agentId"],
                        context_id=self.context_id, thread_id=self.thread,
                    )
                    await self.receive_passive_context()
                except Exception as error:
                    # Optional observations cannot reject an ordinary admitted task.
                    saved(self.state / "passive-context-gap.json", {
                        "error": type(error).__name__, "executionAdmitted": False,
                        "nativeReplayAllowed": False,
                    })
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
                await self.executor.require_live()
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
                                "causalTaskContext": self.causal_task_context,
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
                current = await self.http(
                    "GET", "deliveries/" + self.active["delivery"]["id"]
                )
                admitted = current["delivery"]
                if (
                    admitted["state"] == "running"
                    and not admitted["cancellation_requested"]
                    and admitted["native_thread"] == self.thread
                    and admitted["native_turn"] == turn_id
                    and admitted["generation"] == self.active["delivery"]["generation"]
                    and admitted["claim_id"] == self.active["delivery"]["claim_id"]
                ):
                    self.tool_admission.set()
                else:
                    raise RuntimeError("Native tool admission changed before callbacks")
                self.control_task = asyncio.create_task(self.monitor_guidance(turn_id))
                turn = await asyncio.wait_for(
                    self.finished, self.config.get("turnDeadlineSeconds")
                )
                if self.interrupt_task:
                    self.interrupt_task.cancel()
                    await asyncio.gather(self.interrupt_task, return_exceptions=True)
                    self.interrupt_task = None
                if self.control_task:
                    self.control_task.cancel()
                    await asyncio.gather(self.control_task, return_exceptions=True)
                    self.control_task = None
                await self.controls.tick(turn_id, terminal=True)
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
            except NativeToolPolicyUnavailable as error:
                current = json.loads(journal.read_text())
                receipt = await self.transition(
                    "failed",
                    nativeThread=self.thread,
                    body="Required native tool ceiling could not be verified; no model turn admitted.",
                )
                saved(
                    journal,
                    {
                        **current,
                        "state": "failed",
                        "modelsStarted": 0,
                        "nativePolicyUnverified": True,
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
            except Exception as error:
                current = json.loads(journal.read_text())
                saved(journal.directory / "execution-error.json", {
                    "phase": current["state"],
                    "error": type(error).__name__,
                    "detail": str(error)[:2000],
                    "nativeThread": self.thread,
                    "nativeTurn": current.get("nativeTurn"),
                    "deliveryId": self.active["delivery"]["id"],
                    "executionNotRepeated": True,
                })
                try:
                    await self.transition("unknown")
                except Exception:
                    pass
                # Durable native intent is left unsettled for operator/native readback.
                raise
            finally:
                if self.control_task:
                    self.control_task.cancel()
                    await asyncio.gather(self.control_task, return_exceptions=True)
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
                await self.executor.observe_close()

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
                            "capabilities": CAPABILITIES,
                        },
                    )
                    await self.http(
                        "POST",
                        "connector/supervision",
                        {
                            "hostId": self.config["hostId"],
                            "capabilities": CAPABILITIES,
                        },
                    )
                    projection = await self.http(
                        "POST",
                        "connector/observe",
                        {
                            "hostId": self.config["hostId"],
                            "capabilities": CAPABILITIES,
                        },
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
                    and projection["eligibleDeliveryId"]
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
                    {
                        "state": "waiting",
                        "modelsStartedByObservation": 0,
                        "admission": projection,
                    },
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
    action.add_argument("--reconcile-delivery", metavar="DELIVERY_ID")
    action.add_argument("--list-attempts", action="store_true")
    parser.add_argument("--generation", type=int)
    action.add_argument("--reconcile-guidance", metavar="CONTROL_ID")
    action.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if bool(args.reconcile_delivery) != (args.generation is not None):
        parser.error("--reconcile-delivery requires --generation; neither starts a model")
    config = json.loads(args.config.read_text())
    package = None
    if args.serve or args.claim_id:
        from .native_package import inspect_package
        # Fail before queue admission, native startup or model sampling.
        package = inspect_package(config["binary"])
    connector = Connector(config)
    if package is not None:
        saved(connector.state / "native-package-preflight.json", package)
    if args.list_attempts:
        print(json.dumps({
            "attempts": [
                {
                    "deliveryId": value["delivery"]["id"],
                    "generation": value["delivery"]["generation"],
                    "state": value["state"],
                    "nativeThread": value.get("nativeThread"),
                    "nativeTurn": value.get("nativeTurn"),
                }
                for value in connector.executions.records()
            ],
            "current": connector.executions.selected_key(),
            "modelsStarted": 0,
        }))
        return
    print(
        json.dumps(
            asyncio.run(
                connector.serve()
                if args.serve
                else connector.reconcile_guidance(args.reconcile_guidance)
                if args.reconcile_guidance
                else connector.reconcile_attempt(args.reconcile_delivery, args.generation)
                if args.reconcile_delivery
                else connector.reconcile()
                if args.reconcile
                else connector.once(args.claim_id)
            )
        )
    )


if __name__ == "__main__":
    main()
