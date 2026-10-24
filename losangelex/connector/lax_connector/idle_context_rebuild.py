"""Original-operation idle replacement on the native canonical transaction.

Existing native history, H rebuild_requested and context operation receipts own
the durable facts. This adapter never creates a turn, repeats a reset, or treats
an acknowledgement write as evidence that the native side received it.
"""
import asyncio
import hashlib
import json

from .automatic_refill_data import CUT, IDENTITY, INSTALLED, parameters, require
from .automatic_refill_history import capture, recovered_installed, verify
from .automatic_refill_recovery import connection
from .journal import saved
from .retained_context_packet import enabled, frame

INSTALL = "thread/contextWindow/idleInstalled"
SCHEMA = "lax-native-idle-context-installed/v1"


class IdleContextRebuild:
    def __init__(self, runner):
        self.runner = runner
        self.root = runner.state / "context-rebuild"
        self.pending = None
        self.epoch = None
        self.recovering = False
        self.held = any(self.owned(value) and value.get("state") != "native_result_confirmed"
                        for path in self.root.glob("*.json")
                        for value in [json.loads(path.read_text())])

    @staticmethod
    def owned(value):
        return value.get("nativeContextMode") == "idle_request" and value.get("schema") == SCHEMA

    @property
    def blocked(self):
        return self.held or self.recovering or self.pending is not None

    def path(self, operation):
        return self.root / (hashlib.sha256(operation.encode()).hexdigest() + ".json")

    def owns(self, operation):
        path = self.path(operation)
        return path.exists() and self.owned(json.loads(path.read_text()))

    def save(self, operation, state=None, **updates):
        operation.update(updates)
        if state is not None:
            operation["state"] = state
        saved(self.path(operation["operationId"]), operation)

    def check(self, operation):
        r = self.runner
        require(self.pending is operation and not self.held
                and not r.active and not r.accepting and not r.closing and not r.failed
                and not r.agent.stop.is_set() and connection(r) == self.epoch,
                "Original idle operation or owner connection changed")

    def hold(self, operation, error):
        self.held = True
        self.runner.failed = True
        self.runner.failure_reason = "Original idle context outcome held: " + str(error)
        self.save(operation, "held", holdReason=str(error)[:1000])

    async def rebuild(self, request_id, pending):
        r = self.runner
        require(enabled(r) and getattr(r, "retained_context_contract", False),
                "Paired native idle Writer profile is not installed")
        key = hashlib.sha256((r.config["contextIds"][r.purpose] + ":" + request_id).encode()).hexdigest()
        native_op = "context-refill-native:" + key
        async with r.effect_lock:
            require(not r.automatic.blocked and not r.active and not r.accepting
                    and not r.closing and not r.failed and not r.agent.stop.is_set(),
                    "Original context is not quiescent")
            require(not self.path(native_op).exists(),
                    "Original rebuild exists; inspect its receipt, never repeat replacement")
            self.root.mkdir(mode=0o700, exist_ok=True)
            operation = {"schema": SCHEMA, "nativeContextMode": "idle_request",
                "operationId": native_op, "requestOperationId": request_id,
                "snapshotOperationId": "context-refill-snapshot:" + key,
                "installedOperationId": "context-refill-installed:" + key,
                "nativeThread": r.thread, "agentId": r.config["agentId"],
                "contextId": r.config["contextIds"][r.purpose], "purpose": r.purpose}
            self.pending = operation
            self.epoch = connection(r)
            self.save(operation, "intent")
        try:
            # All serialized native observations precede the mutating RPC. Its
            # installed callback cannot reenter thread/read or contextWindow/read.
            observed = await r.rpc.call("thread/read", {"threadId": r.thread, "includeTurns": False})
            original = await asyncio.to_thread(capture, observed["thread"], r.thread)
            cut = (await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]
            require(cut["idle"] is True and cut["activeTurnId"] is None
                    and cut["heldOperationId"] is None and cut["lastStartedTurnId"]
                    and cut["threadId"] == r.thread
                    and cut["contextId"] == operation["contextId"] and cut["purpose"] == r.purpose,
                    "Original native window is not an owned idle cut")
            request = {key: cut[key] for key in ("threadId", "contextId", "purpose",
                                                "windowId", "historyVersion")}
            request.update(operationId=native_op, turnId=cut["lastStartedTurnId"],
                           reason="explicitRequest", phase="postTurn")
            async with r.effect_lock:
                self.check(operation)
                self.save(operation, "snapshot_intent", originalHistory=original,
                          request=request, nativeState=cut)
            selected = [item["id"] for item in pending if not item["cancelled"]][:1]
            snapshot = await r.request("rebuild_snapshot", {"materialIds": selected},
                operation=operation["snapshotOperationId"], turn=request["turnId"])
            from .context_action_memory import index
            content = json.loads("".join(chunk["content"] for chunk in snapshot["chunks"]))
            actions = await asyncio.to_thread(index, r, content)
            response, budget = await frame(r, snapshot, request, actions)
            preflight = (await r.rpc.call("thread/contextWindow/preflight", {
                "threadId": r.thread, "state": cut, "packet": response}))["preflight"]
            require(preflight["state"] == cut and preflight["operationId"] == native_op,
                    "Native preflight belongs to another original cut")
            async with r.effect_lock:
                self.check(operation)
                self.save(operation, "native_dispatch_intent", response=response,
                          preflight=preflight, retainedBudget=budget, snapshot=snapshot)
            # No effect_lock across this wait. Unknown outcome keeps the original
            # journal/gate; caller must observe it, never send another replacement.
            result = await r.rpc.call("thread/contextWindow/replaceIdle", {
                "threadId": r.thread, "preflight": preflight, "packet": response}, timeout=75)
            async with r.effect_lock:
                self.check(operation)
                require(result["receipt"] == operation.get("installed")
                        and operation.get("hostReceipt", {}).get("status") == "recorded",
                        "Original native result or H receipt differs")
                self.save(operation, "native_result_confirmed", nativeResult=result)
                receipt = operation["hostReceipt"]
                saved(r.state / "context-rebuild-generation.json", receipt)
                self.pending = None
                self.epoch = None
            r.trace("native_idle_context_rebuilt", {
                "operationId": native_op, "windowId": result["receipt"]["windowId"],
                "generation": receipt["generation"]})
            return receipt
        except BaseException as error:
            async with r.effect_lock:
                if self.pending is operation:
                    self.hold(operation, error)
            raise

    async def callback(self, raw):
        r = self.runner
        require("_rpcRequestId" in raw, "Original native callback identity missing")
        params = {key:value for key,value in raw.items() if key != "_rpcRequestId"}
        parameters(params, INSTALLED)
        async with r.effect_lock:
            operation = self.pending
            require(operation is not None, "No original idle install awaits acknowledgement")
            self.check(operation)
            response = operation["response"]
            require(all(params[key] == response[key] for key in IDENTITY | CUT)
                    and params["previousWindowId"] == operation["request"]["windowId"],
                    "Native idle installed receipt differs from original packet")
            require("installRpcId" not in operation, "Original idle callback already observed")
            self.save(operation, "history_verifying", installed=params,
                      installRpcId=raw["_rpcRequestId"])
        await asyncio.to_thread(verify, operation["originalHistory"], operation["request"],
            response, params, native_mode="idle_request")
        async with r.effect_lock:
            self.check(operation)
            self.save(operation, "host_ack_intent")
        receipt = await r.request("rebuild_installed", {
            "schema": SCHEMA, "snapshotOperationId": operation["snapshotOperationId"],
            "nativeReceipt": params, "preflight": operation["preflight"]},
            operation=operation["installedOperationId"], turn=params["turnId"])
        async with r.effect_lock:
            self.check(operation)
            require(receipt.get("schema") == SCHEMA and receipt.get("status") == "recorded"
                    and receipt["nativeReceipt"] == params
                    and receipt["preflight"] == operation["preflight"],
                    "Original Hollywood idle installation is not recorded")
            self.save(operation, "host_ack_recorded", hostReceipt=receipt)
        return {"operationId": params["operationId"], "status": "recorded"}

    async def submitted(self, raw, success):
        operation_id = raw.get("operationId")
        if not operation_id or not self.owns(operation_id):
            return
        async with self.runner.effect_lock:
            operation = self.pending
            if operation is None or operation["operationId"] != operation_id:
                return  # completed/cold state is observed through its original receipt
            require(raw.get("_rpcRequestId") == operation.get("installRpcId"),
                    "Idle acknowledgement write belongs to another request")
            self.save(operation, ackWriteObserved=bool(success))
            if not success and operation.get("nativeResult") is None:
                self.hold(operation, "Original idle acknowledgement write outcome unknown")

    async def observe(self, path, native=None):
        r = self.runner
        captured = connection(r)
        original_bytes = path.read_bytes()
        operation = json.loads(original_bytes)
        require(self.owned(operation) and operation["agentId"] == r.config["agentId"]
                and operation["contextId"] == r.config["contextIds"][r.purpose]
                and operation["nativeThread"] == r.thread and operation["purpose"] == r.purpose,
                "Original idle receipt belongs to another owner")
        installed = operation.get("installed")
        if installed is None:
            installed = await asyncio.to_thread(recovered_installed,
                operation["originalHistory"], operation["operationId"])
        parameters(installed, INSTALLED)
        require(native is None or native == installed, "Recovered native idle receipt differs")
        await asyncio.to_thread(verify, operation["originalHistory"], operation["request"],
            operation["response"], installed, native_mode="idle_request")
        try:
            receipt = await r.agent.http(r.purpose, "GET",
                f"agents/{r.config['agentId']}/contexts/{r.purpose}/operations/" +
                operation["installedOperationId"])
        except Exception as error:
            from .errors import HttpFailure
            # Native committed and synced the exact original checkpoint before
            # asking for acknowledgement. A lost/locally refused first callback
            # may therefore have no Hollywood metadata receipt yet. Complete
            # only that metadata transaction after independent file proof;
            # never send another native replacement or inference.
            require(isinstance(error, HttpFailure) and error.status == 404
                    and error.code == "CONTEXT_OPERATION_NOT_FOUND"
                    and operation.get("state") in (
                        "native_dispatch_intent", "history_verifying", "held")
                    and operation.get("hostReceipt") is None,
                    "Original Hollywood idle receipt unavailable; no metadata completion")
            require(not r.agent.stop.is_set() and connection(r) == captured
                    and path.read_bytes() == original_bytes,
                    "Original idle owner changed before metadata completion")
            receipt = await r.request("rebuild_installed", {
                "schema": SCHEMA,
                "snapshotOperationId": operation["snapshotOperationId"],
                "nativeReceipt": installed,
                "preflight": operation["preflight"]},
                operation=operation["installedOperationId"], turn=installed["turnId"])
        require(receipt.get("schema") == SCHEMA and receipt.get("status") == "recorded"
                and receipt["nativeReceipt"] == installed
                and receipt["preflight"] == operation["preflight"]
                and receipt["snapshotOperationId"] == operation["snapshotOperationId"],
                "Original Hollywood idle receipt is not recorded")
        require(not r.agent.stop.is_set() and connection(r) == captured
                and path.read_bytes() == original_bytes,
                "Original idle connection or journal changed during observation")
        return {"operationId": operation["operationId"], "status": "recorded"}

    async def reconcile(self, raw):
        require("_rpcRequestId" in raw, "Original reconciliation callback missing")
        params = {key:value for key,value in raw.items() if key != "_rpcRequestId"}
        parameters(params, INSTALLED)
        return await self.observe(self.path(params["operationId"]), params)

    async def startup(self):
        unresolved = []
        self.recovering = True
        try:
            for path in sorted(self.root.glob("*.json")):
                value = json.loads(path.read_text())
                if not self.owned(value):
                    continue
                try:
                    await self.observe(path)
                except Exception as error:
                    unresolved.append({"operationId": value["operationId"], "reason": str(error)})
            self.held = bool(unresolved)
            if unresolved:
                self.runner.failed = True
                self.runner.failure_reason = "Original native idle receipt unresolved: " + unresolved[0]["reason"]
            if self.root.exists():
                saved(self.runner.state / "native-idle-recovery.json", {
                    "unresolved": unresolved, "originalJournalsRewritten": False})
        finally:
            self.recovering = False
