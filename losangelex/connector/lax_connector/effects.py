"""Scoped original HTTP evidence. Recovery reads receipts; it never invokes a tool again."""
import contextlib
import contextvars
import hashlib
import json
from .journal import saved
from .errors import HttpFailure
from .tool_execution import participation

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def parsed(value):
    return json.loads(value) if isinstance(value, str) else value

ATOMIC = {
    "hollywood_briefing",
    "hollywood_publish", "hollywood_request", "hollywood_decision_set",
    "hollywood_cooperation_set", "hollywood_work_create", "hollywood_work_assign",
    "hollywood_work_claim", "hollywood_work_report", "hollywood_work_report_reconcile", "hollywood_work_review",
    "hollywood_work_cancel", "hollywood_work_revise", "hollywood_work_recover",
}

ADMIN_STAGES = {
    "hollywood_mutation_reconcile": {"mutation-reconcile"},
    "hollywood_create_agent": {"principal", "role"},
    "hollywood_create_room": {"room"},
    "hollywood_set_role": {"role"},
    "hollywood_grant_room": {"membership"},
    "hollywood_grant_resource": {"resource-grant"},
    "hollywood_select_resource_default": {"resource-default"},
    "hollywood_placement_set": {"placement-state"},
    "lax_provision_worker": {"placement","purpose-context"},
    "hollywood_reconcile_pending_inputs": {"purpose-context"},
    "hollywood_select_work_resource": {"work-resource"},
}

class Effects:
    def __init__(self, connector):
        self.c = connector
        self.current = contextvars.ContextVar("lax_original_tool_effect", default=None)

    @contextlib.contextmanager
    def tool_scope(self, method, params):
        c = self.c
        if method != "item/tool/call":
            yield
            return
        owner = c.captured_execution()
        if (not owner["nativeThread"] or not owner["nativeTurn"]
                or params["threadId"] != owner["nativeThread"]
                or params.get("turnId", owner["nativeTurn"]) != owner["nativeTurn"]):
            raise RuntimeError("Tool belongs to another native context")
        key = hashlib.sha256((params["threadId"] + params["callId"]).encode()).hexdigest()
        binding = c.goal_binding
        scope = {
            "authorityId": owner["request"]["authority"], "agentId": c.config["agentId"],
            "hostId": c.config["hostId"], "deliveryId": owner["delivery"]["id"],
            "claimId": owner["delivery"]["claim_id"], "generation": owner["delivery"]["generation"],
            "requestId": owner["request"]["id"], "nativeThread": c.thread,
            "nativeTurn": owner["nativeTurn"], "callId": params["callId"],
            "tool": params["tool"],
            "roleRevision": c.role_context.value["roleRevision"],
            "contextId": c.context_id,
            "nativeGoalId": binding["nativeGoalId"] if binding else None,
            "argumentsDigest": hashlib.sha256(json.dumps([params["tool"], params["arguments"]], sort_keys=True).encode()).hexdigest(),
            "bindingAtStart": {k: binding.get(k) for k in ("bindingKind", "goalId", "nativeGoalId")} if binding else None,
        }
        token = self.current.set({"key": key, "scope": scope, "owner": owner})
        try:
            yield
        finally:
            self.current.reset(token)

    def before(self, method, path, payload):
        context = self.current.get()
        if not context or method not in ("POST", "PUT"):
            return None
        key, scope = context["key"], context["scope"]
        tool_path = self.c.state / ("tool-" + key + ".json")
        tool = json.loads(tool_path.read_text())
        if tool["digest"] != scope["argumentsDigest"] or tool["requestId"] != scope["requestId"]:
            raise RuntimeError("Tool mutation scope changed")
        journal = self.c.state / ("effects-" + key + ".json")
        group = json.loads(journal.read_text()) if journal.exists() else {"schema": "lax-tool-effects/v1", "scope": scope, "steps": []}
        if group["scope"] != scope:
            raise RuntimeError("Original tool effects changed scope")
        wire = json.loads(json.dumps({"method": method, "path": path, "body": payload}))
        operation = payload.get("operationId") if isinstance(payload, dict) else None
        supported = operation == "lax-tool:" + key
        administrative = operation in {
            "lax-tool:" + key + ":admin:" + stage
            for stage in ADMIN_STAGES.get(scope["tool"], ())
        }
        step = {
            "ordinal": len(group["steps"]), "state": "intent", "method": method, "path": path,
            "operationId": operation, "wireDigest": digest(wire),
            # Unsupported administrative requests can contain enrollment credentials.
            "wireRequest": wire if supported else None, "receiptSupported": supported,
            "administrativeReceiptSupported": administrative,
        }
        group["steps"].append(step)
        saved(journal, group)
        return journal, step["ordinal"]

    def after(self, marker, *, result=None, error=None):
        if marker is None:
            return
        path, index = marker
        group = json.loads(path.read_text())
        step = group["steps"][index]
        if error is None:
            step["state"] = "confirmed"
            if step["receiptSupported"] or step.get("administrativeReceiptSupported"):
                step["result"] = result
        else:
            step["state"] = "rejected" if isinstance(error, HttpFailure) and error.status in (400, 403, 409) else "unconfirmed"
            step["error"] = type(error).__name__
        saved(path, group)

    async def recover_http(self, marker):
        """Resolve a committed administrative child, then continue the live parent."""
        context = self.current.get()
        if marker is None or context is None:
            return None
        path, index = marker
        group = json.loads(path.read_text())
        if group["scope"] != context["scope"] or self.current_key(group) != context["key"]:
            raise RuntimeError("Administrative callback scope changed")
        c, scope = self.c, group["scope"]
        owner = participation(c)
        expected = {
            "authorityId": owner["request"]["authority"], "agentId": c.config["agentId"],
            "hostId": c.config["hostId"], "requestId": owner["request"]["id"],
            "deliveryId": owner["delivery"]["id"],
            "claimId": owner["delivery"]["claim_id"],
            "generation": owner["delivery"]["generation"], "nativeThread": c.thread,
        }
        if any(scope.get(k) != v for k, v in expected.items()):
            raise RuntimeError("Administrative operation ownership changed")
        step = group["steps"][index]
        expected_operations = {
            "lax-tool:" + context["key"] + ":admin:" + stage
            for stage in ADMIN_STAGES.get(scope["tool"], ())
        }
        if not step.get("administrativeReceiptSupported") or step["operationId"] not in expected_operations:
            return None
        receipt = await c.http("GET", "administration/commands/" + step["operationId"])
        expected_receipt = {
            "schema": "hollywood-administrative-command/v1",
            "authorityId": scope["authorityId"], "actorId": scope["agentId"],
            "operationId": step["operationId"], "method": step["method"],
            "path": step["path"], "wireDigest": step["wireDigest"],
        }
        if any(receipt.get(k) != v for k, v in expected_receipt.items()):
            raise RuntimeError("Original administrative acceptance conflicts")
        if step["state"] == "confirmed" and step.get("result") != receipt["acceptedResult"]:
            raise RuntimeError("Original administrative result conflicts")
        step.update(state="confirmed", result=receipt["acceptedResult"],
                    recoveredBy="original-administrative-command-read")
        saved(path, group)
        return receipt["acceptedResult"]

    def group(self, key):
        path = self.c.state / ("effects-" + key + ".json")
        return json.loads(path.read_text()) if path.exists() else None

    def safe_rejection(self):
        context = self.current.get()
        if not context:
            return False
        group = self.group(context["key"])
        return not group or not group["steps"] or all(s["state"] == "rejected" for s in group["steps"])

    def atomic(self, group):
        name = group["scope"]["tool"]
        if name in ATOMIC or ((self.c.agent_binding or getattr(self.c,"purpose_scope",None)) and name in ("hollywood_goal_create","hollywood_goal_state")):
            return True
        binding = group["scope"]["bindingAtStart"]
        if binding is not None:
            current = self.c.goal_binding
            if not current or binding != {k: current.get(k) for k in ("bindingKind", "goalId", "nativeGoalId")}:
                return False
        if name == "hollywood_goal_create":
            return binding is not None
        if name == "hollywood_goal_state":
            args = parsed(json.loads((self.c.state / ("tool-" + self.current_key(group) + ".json")).read_text())["arguments"])
            return not binding or binding["bindingKind"] == "role" or binding["goalId"] != args["goalId"] or args["state"] == "accepted"
        return False

    @staticmethod
    def current_key(group):
        s = group["scope"]
        return hashlib.sha256((s["nativeThread"] + s["callId"]).encode()).hexdigest()

    async def resolve(self, group):
        c = self.c
        scope = group["scope"]
        owner = participation(c)
        expected = {
            "authorityId": owner["request"]["authority"], "agentId": c.config["agentId"],
            "hostId": c.config["hostId"], "deliveryId": owner["delivery"]["id"],
            "claimId": owner["delivery"]["claim_id"], "generation": owner["delivery"]["generation"],
            "requestId": owner["request"]["id"], "nativeThread": c.thread,
        }
        if any(scope.get(k) != v for k, v in expected.items()):
            raise RuntimeError("Original command effect ownership changed")
        if len(group["steps"]) != 1 or not group["steps"][0]["receiptSupported"] or not self.atomic(group):
            return None
        step = group["steps"][0]
        if (
            step["operationId"] != "lax-tool:" + self.current_key(group)
            or digest(step["wireRequest"]) != step["wireDigest"]
            or step["wireRequest"]["method"] != step["method"]
            or step["wireRequest"]["path"] != step["path"]
            or step["wireRequest"]["body"].get("operationId") != step["operationId"]
        ):
            raise RuntimeError("Original command request changed")
        receipt = await c.http("GET", "commands/" + step["operationId"])
        evidence = receipt.get("canonicalCommand")
        if not evidence or not evidence.get("evidenceComplete"):
            return None
        expected_evidence = {
            "schema": "hollywood-command/v1", "authorityId": scope["authorityId"],
            "actorId": scope["agentId"], "operationId": step["operationId"],
            "wireRequest": step["wireRequest"], "wireDigest": step["wireDigest"],
        }
        if any(evidence.get(k) != v for k, v in expected_evidence.items()):
            raise RuntimeError("Authoritative command evidence conflicts")
        if receipt["event"]["id"] != evidence["eventId"] or receipt["event"]["author"] != scope["agentId"]:
            raise RuntimeError("Original command event changed")
        if step["state"] == "confirmed" and step.get("result") != evidence["acceptedResult"]:
            raise RuntimeError("Original accepted response conflicts")
        step.update(state="confirmed", result=evidence["acceptedResult"], recoveredBy="original-command-read")
        saved(c.state / ("effects-" + self.current_key(group) + ".json"), group)
        return evidence["acceptedResult"]

    def completed_administration(self, key, name):
        if name not in ("hollywood_create_agent", "hollywood_create_room", "hollywood_set_role", "hollywood_grant_room", "hollywood_grant_resource", "hollywood_select_resource_default", "hollywood_placement_set", "hollywood_mutation_observe", "hollywood_mutation_reconcile", "lax_provision_worker", "hollywood_reconcile_pending_inputs", "hollywood_select_work_resource"):
            return None
        operation = "lax-tool:" + key
        path = self.c.state / ("administration-" + hashlib.sha256(operation.encode()).hexdigest() + ".json")
        if not path.exists():
            return None
        record = json.loads(path.read_text())
        if record.get("operationId") != operation or record.get("tool") != name:
            raise RuntimeError("Original administration journal identity changed")
        if record["state"] == "completed":
            return record["result"]
        return None  # An unfinished multi-step workflow is not an atomic rejection.

    async def recover_live(self):
        context = self.current.get()
        if not context:
            return None
        admin = self.completed_administration(context["key"], context["scope"]["tool"])
        if admin is not None:
            return admin
        group = self.group(context["key"])
        if not group:
            return None
        return await self.resolve(group)

    async def reconcile(self, execution, turn):
        """Reconcile failed original callbacks using accepted effects, not current file contents."""
        c = self.c
        owner = participation(c)
        items = {item["id"]: item for item in turn.get("items", [])}
        recovered = []
        for path in sorted(c.state.glob("tool-*.json")):
            tool = json.loads(path.read_text())
            if tool["state"] == "completed" or tool.get("requestId") != owner["request"]["id"] or tool.get("nativeThread") != execution["nativeThread"]:
                continue
            if tool.get("nativeTurn", execution["nativeTurn"]) != execution["nativeTurn"]:
                continue
            item = items.get(tool["callId"])
            if not item or item.get("type") != "dynamicToolCall" or item.get("tool") != tool["tool"]:
                continue
            if not (item.get("status") in ("failed", "declined") or item.get("status") == "completed" and item.get("success") is False):
                continue
            if parsed(item.get("arguments")) != parsed(tool["arguments"]):
                raise RuntimeError("Original native tool arguments conflict")
            key = hashlib.sha256((tool["nativeThread"] + tool["callId"]).encode()).hexdigest()
            fingerprint = hashlib.sha256(json.dumps([tool["tool"], tool["arguments"]], sort_keys=True).encode()).hexdigest()
            if path.name != "tool-" + key + ".json" or fingerprint != tool["digest"]:
                raise RuntimeError("Original tool journal identity changed")
            from .workflow import READ_TOOLS
            read_only = tool["tool"] in READ_TOOLS | {"hollywood_context", "hollywood_rooms", "hollywood_read_room", "hollywood_room_info", "hollywood_agent_info"}
            group = self.group(key)
            # Reporting prepares/hash-reads evidence before its sole mutating
            # HTTP call. before() durably journals that call BEFORE transport.
            # A verified failed native report callback with no effect group
            # therefore never reached report dispatch. This exception is narrow:
            # provisioning/native mutations without a group remain unknown.
            report_pre_dispatch = tool["tool"] == "hollywood_work_report" and group is None
            if read_only or report_pre_dispatch:
                value = {"effect": "none", "observation": (
                    "Original report callback failed before any mutating HTTP dispatch; no report was replayed"
                    if report_pre_dispatch else "Original read callback failed; no read was replayed")}
            else:
                if (
                    not group or group["scope"]["nativeTurn"] != execution["nativeTurn"]
                    or group["scope"]["argumentsDigest"] != fingerprint
                    or group["scope"]["callId"] != tool["callId"]
                    or group["scope"]["tool"] != tool["tool"]
                    or group["scope"]["deliveryId"] != owner["delivery"]["id"]
                    or group["scope"]["generation"] != owner["delivery"]["generation"]
                    or group["scope"]["claimId"] != owner["delivery"]["claim_id"]
                    or group["scope"]["agentId"] != c.config["agentId"]
                    or group["scope"]["hostId"] != c.config["hostId"]
                ):
                    continue
                value = self.completed_administration(key, tool["tool"])
                if value is None:
                    value = await self.resolve(group)
                if value is None:
                    continue
            result = {
                "success": False,
                "contentItems": [{"type": "inputText", "text": json.dumps({
                    "effect": "none" if read_only or report_pre_dispatch else "confirmed-from-original-receipt", "receipt": value,
                    "nativeCallbackReplayed": False, "originalNativeCallbackFailed": True,
                })}],
            }
            saved(path, {**tool, "state": "completed", "result": result, "effectReconciled": True, "nativeCallbackReplayed": False})
            recovered.append({"callId": tool["callId"], "tool": tool["tool"], "operationId": "lax-tool:" + key, "nativeCallbackReplayed": False})
        return recovered


def native_source(scope, *, purpose=None, agent_binding=False):
    fields=("authorityId","agentId","hostId","deliveryId","claimId","generation","requestId",
            "nativeThread","nativeTurn","callId","tool","argumentsDigest","roleRevision","contextId","nativeGoalId")
    value={"schema":"hollywood-native-source/v3" if purpose else
           "hollywood-native-source/v2" if agent_binding else "hollywood-native-source/v1",
           **{k:scope[k] for k in fields}}
    if purpose:
        value.update(executionScopeId=purpose["id"],executorId=purpose["executorId"])
    return value
