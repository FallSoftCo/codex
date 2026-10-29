"""Same-live-turn automatic canonical refill; no compact/start or inject fallback.

The logical operation gate survives response writes without holding effect_lock.
Unknown outcomes retain the original journal and gate; restart never replays.
"""
import asyncio
import hashlib
import json

from .automatic_refill_data import (
    CUT, IDENTITY, INSTALLED, REFILL, identifier, parameters, render, require, unsigned,
)
from .automatic_refill_history import capture, verify
from .journal import saved

PREPARE = "thread/contextWindow/refill"
INSTALL = "thread/contextWindow/installed"
from .automatic_refill_recovery import RECONCILE
from .idle_context_rebuild import INSTALL as IDLE_INSTALL, IdleContextRebuild
METHODS = (PREPARE, INSTALL, RECONCILE, IDLE_INSTALL)


class AutomaticContextRefill:
    def __init__(self, runner):
        self.runner = runner
        self.pending = None
        self.held = False
        self.recovering = False
        self.timer = None
        self.owner_epoch = None
        self.prepare_written = None
        self.install_started = False
        self.original_binding = None
        self.root = runner.state / "automatic-context-refill"
        self.root.mkdir(mode=0o700, exist_ok=True)
        # An installed host receipt is not proof its native acknowledgement was
        # received. Even acknowledged journals are never submitted a second time.
        for path in self.root.glob("*.json"):
            if json.loads(path.read_text())["state"] != "ack_written":
                self.held = True
        self.idle = IdleContextRebuild(runner)
        from .native_context_acquisition import NativeContextAcquisition
        self.acquisition = NativeContextAcquisition(runner)
        # Startup observes the original receipt before attributing this hold.
        # It never clears independent reader/tool/effect failure causes.

    @property
    def blocked(self):
        return self.held or self.recovering or self.pending is not None or self.idle.blocked or self.acquisition.blocked

    def policy(self):
        from .retained_context_packet import enabled, CAPABILITY
        whole = enabled(self.runner)
        value = self.runner.config.get("automaticContextRefill")
        if value is None or value == {"type": "disabled"}:
            require(not whole, "Whole-native retention requires canonical refill")
            return None
        require(isinstance(value, dict) and set(value) == {"type"}
                and value["type"] == "canonical", "Explicit canonical opt-in required")
        context = identifier(self.runner.config["contextIds"][self.runner.purpose])
        if whole:
            require(CAPABILITY in self.runner.rpc.lax_capabilities,
                    "Paired native retained Writer context capability unavailable")
        return {"type": "canonicalRetainedActions" if whole else "canonical",
                "contextId": context, "purpose": self.runner.purpose}

    def live(self, owner=None):
        r = self.runner
        require(not self.held and r.active and r.accepting and not r.closing
                and not r.failed and not r.agent.stop.is_set()
                and r.finished is not None and not r.finished.done(),
                "Original automatic refill owner is not accepting")
        current = {"agentId": identifier(r.config["agentId"]),
                   "contextId": identifier(r.config["contextIds"][r.purpose]),
                   "purpose": r.purpose, "threadId": identifier(r.thread),
                   "turnId": identifier(r.turn), "permitId": identifier(r.permit),
                   "materialIds": list(r.material_ids)}
        ids = current["materialIds"]
        require(ids and len(ids) <= 100 and len(set(ids)) == len(ids),
                "Exact bounded active material identities required")
        for identity in ids:
            identifier(identity)
        original = list(r.permit_material_ids)
        require(set(original) <= set(ids) if r.purpose == "reader" else original == ids,
                "Active material identities differ from original permit")
        if r.execution_scope is not None:
            scope = r.execution_scope.as_dict()
            require(all(scope[k] == current[v] for k, v in (
                ("agentId", "agentId"), ("contextId", "contextId"),
                ("purpose", "purpose"), ("nativeThread", "threadId"),
                ("nativeTurn", "turnId"))) and [scope["materialId"]] == ids,
                "Captured writer execution scope differs")
        if r.inbox:
            require(not r.inbox.uncertain, "Original inbox append/adopt outcome is unknown")
        if owner is not None:
            require(current == owner, "Original automatic refill owner changed")
        return current

    def save(self, state, **updates):
        self.pending.update(updates, state=state)
        saved(self.path, self.pending)

    def epoch(self):
        r = self.runner
        # Pin actual connection/process/reader and live-turn objects, not merely
        # IDs that another connection could present. These references stay local.
        return (r.rpc, getattr(r.rpc, "process", None), getattr(r.rpc, "reader", None),
                r.finished, r.execution_scope, r.inbox, tuple(r.permit_material_ids))

    def check(self, operation, phase):
        require(self.pending is operation, "Original operation gate changed")
        self.live(operation["owner"])
        epoch = self.epoch()
        require(all(a is b for a, b in zip(epoch[:-1], self.owner_epoch[:-1]))
                and epoch[-1] == self.owner_epoch[-1], "Original owner connection epoch changed")
        require(json.dumps([operation["request"], operation["owner"]], sort_keys=True)
                == self.original_binding, "Original operation binding changed")
        require(operation["state"] == phase, "Original operation phase changed")

    def hold(self, reason):
        first = not self.held
        self.held = True
        self.runner.failed = True
        self.runner.accepting = False
        try:
            if first and self.pending is not None:
                self.save("held", holdReason=reason)
        finally:
            # Wake concurrent installed callbacks even if persistence failed.
            # The original pre-ack journal still fences restart; never replay.
            if self.prepare_written is not None:
                self.prepare_written.set()
        self.runner.trace("automatic_refill_held", {"reason": reason,
                          "effectsReplayed": False})

    async def deadline(self):
        await asyncio.sleep(60)
        async with self.runner.effect_lock:
            if self.pending is not None:
                self.hold("Original automatic refill installation/ack timeout")

    async def call(self, method, raw):
        if method == IDLE_INSTALL:
            return await self.idle.callback(raw)
        if method == RECONCILE and self.idle.owns(raw.get("operationId", "")):
            return await self.idle.reconcile(raw)
        if method == RECONCILE:
            from .automatic_refill_recovery import callback
            return await callback(self, raw)
        await self.runner.admitted.wait()
        try:
            async with self.runner.effect_lock:
                require(self.policy() is not None, "Automatic canonical refill is disabled")
                require("_rpcRequestId" in raw, "Original RPC request identity missing")
                params = {k: v for k, v in raw.items() if k != "_rpcRequestId"}
                parameters(params, REFILL if method == PREPARE else INSTALLED)
                owner = self.live()
                require(all(params[k] == owner[k] for k in
                            ("threadId", "turnId", "contextId", "purpose")),
                        "Automatic callback belongs to another owner")
                if method == PREPARE:
                    require(not self.blocked, "Original automatic refill already open/held")
                    self.path = self.root / (hashlib.sha256(params["operationId"].encode()).hexdigest() + ".json")
                    require(not self.path.exists(), "Original automatic operation exists; inspect, never replay")
                    self.pending = {"state": "intent", "request": params, "owner": owner,
                                    "prepareRpcId": raw["_rpcRequestId"]}
                    self.owner_epoch = self.epoch()
                    self.original_binding = json.dumps([params, owner], sort_keys=True)
                    self.prepare_written = asyncio.Event()
                    self.install_started = False
                    self.save("intent")
                    self.timer = asyncio.create_task(self.deadline())
                else:
                    require(self.pending is not None and not self.install_started,
                            "No original refill awaits its first installation callback")
                    self.check(self.pending, self.pending["state"])
                    require(self.pending["state"] in ("response_prepared", "response_written"),
                            "No original prepared refill awaits installation")
                    require(params["operationId"] == self.pending["request"]["operationId"],
                            "Installed operation differs")
                    self.install_started = True
                    self.save(self.pending["state"], installRpcId=raw["_rpcRequestId"])
                operation = self.pending
            # A durable operation-owned gate, NOT a network-held mutex, excludes
            # append/adopt and tools across all observation and HTTP waits.
            if method == PREPARE:
                return await self.prepare(operation)
            # Native may see the response before transport drain/on_submission.
            # Wait for that original local write outcome, never infer installation
            # from it. A lost/failed write or cancellation wakes into a held check.
            await self.prepare_written.wait()
            async with self.runner.effect_lock:
                self.check(operation, "response_written")
                self.save("install_observing")
            return await self.install(params, operation)
        except BaseException as error:
            async with self.runner.effect_lock:
                if self.pending is not None:
                    self.hold(type(error).__name__)
            raise

    def render_snapshot(self, snapshot, params, owner):
        # Potentially large provenance scans run off-lock/off-loop. Only data
        # bound to the captured owner is returned; reentry validates it again.
        render(snapshot, params["operationId"], [])
        content = json.loads("".join(chunk["content"] for chunk in snapshot["chunks"]))
        require(all(content[k] == owner[v] for k, v in (
                    ("agentId", "agentId"), ("contextId", "contextId"),
                    ("purpose", "purpose"), ("nativeThread", "threadId")))
                and content["nextMaterialIds"] == owner["materialIds"],
                "Canonical snapshot belongs to another purpose/material set")
        from .context_action_memory import index
        actions = index(self.runner, content) if owner["purpose"] == "writer" else []
        items, action_digest = render(snapshot, params["operationId"], actions)
        response = {k: params[k] for k in IDENTITY | {"windowId", "historyVersion"}}
        response.update(snapshotOperationId=params["operationId"],
            snapshotReadPoint=identifier(snapshot["snapshotReadPoint"]),
            snapshotSha256=snapshot["sha256"], nativeActionsSha256=action_digest,
            selectionRevision=unsigned(snapshot["selectionRevision"]),
            totalBytes=snapshot["totalBytes"], items=items)
        return response, actions

    async def prepare(self, operation):
        r = self.runner
        owner, params = operation["owner"], operation["request"]
        rpc = self.owner_epoch[0]
        observed = await rpc.call("thread/read", {"threadId": owner["threadId"], "includeTurns": False})
        async with r.effect_lock:
            self.check(operation, "intent")
            self.save("history_observing")
        original = await asyncio.to_thread(capture, observed["thread"], owner["threadId"])
        async with r.effect_lock:
            self.check(operation, "history_observing")
            self.save("snapshot_intent", originalHistory=original)
        value = {k: owner[k] for k in ("contextId", "permitId", "materialIds")}
        value.update({k: params[k] for k in ("operationId", "windowId", "historyVersion", "reason", "phase")})
        snapshot = await r.request("active_snapshot", value, operation=params["operationId"])
        async with r.effect_lock:
            self.check(operation, "snapshot_intent")
            self.save("snapshot_rendering")
        response, actions = await asyncio.to_thread(self.render_snapshot, snapshot, params, owner)
        from .retained_context_packet import enabled, frame
        extra = {}
        if enabled(r):
            response, budget = await frame(r, snapshot, params, actions)
            extra = {"nativeContextMode": "step_boundary", "retainedBudget": budget}
        async with r.effect_lock:
            self.check(operation, "snapshot_rendering")
            self.save("response_prepared", response=response, nativeActions=actions, **extra)
        return response

    async def install(self, params, operation):
        r = self.runner
        owner = operation["owner"]
        rpc = self.owner_epoch[0]
        observed = await rpc.call("thread/read", {"threadId": owner["threadId"], "includeTurns": False})
        async with r.effect_lock:
            self.check(operation, "install_observing")
            original = operation["originalHistory"]
            require(observed["thread"]["id"] == owner["threadId"]
                    and observed["thread"]["path"] == original["path"]
                    and observed["thread"]["ephemeral"] is False, "Original native history path changed")
            self.save("history_verifying")
        native = {"native_mode": operation["nativeContextMode"]} if "nativeContextMode" in operation else {}
        await asyncio.to_thread(verify, original, operation["request"], operation["response"], params, **native)
        async with r.effect_lock:
            self.check(operation, "history_verifying")
            self.save("host_ack_intent", installed=params)
        value = {k: owner[k] for k in ("contextId", "permitId", "materialIds")}
        value.update({k: params[k] for k in CUT | {
            "operationId", "previousWindowId", "windowId", "nativeHistoryBytes", "nativeHistorySha256"}})
        # request() observes an uncertain original by GET, never repeats POST.
        receipt = await r.request("active_installed", value,
            operation="active-installed:" + hashlib.sha256(params["operationId"].encode()).hexdigest())
        async with r.effect_lock:
            self.check(operation, "host_ack_intent")
            require(receipt["operationId"] == params["operationId"] and receipt["status"] == "recorded",
                    "Original host installation is not accepted")
            self.save("host_ack_recorded", hostReceipt=receipt)
        return {"operationId": params["operationId"], "status": "recorded"}

    async def submitted(self, method, params, success):
        if method == IDLE_INSTALL:
            return await self.idle.submitted(params, success)
        if method not in (PREPARE, INSTALL):
            return
        async with self.runner.effect_lock:
            if self.pending is None:
                return
            key = "prepareRpcId" if method == PREPARE else "installRpcId"
            if params.get("_rpcRequestId") != self.pending.get(key):
                return
            try:
                if not success or self.held:
                    self.hold("Original native response write failed/held")
                    return
                phase = "response_prepared" if method == PREPARE else "host_ack_recorded"
                self.check(self.pending, phase)
                if method == PREPARE:
                    self.save("response_written")  # NOT installation proof
                    self.prepare_written.set()
                else:
                    self.save("ack_written")
                    self.pending = None
                    if self.timer:
                        self.timer.cancel()
                        self.timer = None
            except BaseException as error:
                self.hold(type(error).__name__)
                raise
