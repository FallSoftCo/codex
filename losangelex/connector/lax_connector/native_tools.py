"""Shared native tool dispatch and durable original-operation recovery.

Both native communication modes must use this implementation. The participant
provides captured execution ownership and transport; this module does not select
work, launch models or publish model final text.
"""
import hashlib
import json
from uuid import UUID

from .administration import administer
from .attention import APPROVAL, QUESTION, AttentionExpired
from .continuation_context import LocatorLedger, index_accepted_delegation
from .errors import HttpFailure, ToolValidationError
from .journal import saved
from .participation import initialization, message, history_path
from .workflow import READ_TOOLS, MUTATION_TOOLS, invoke as workflow_tool
from .tool_execution import participation


class NativeTools:
    """Executable tools shared by captured native execution participants."""

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

    async def briefing(self, delivery_id=None):
        # An explicit original-delivery read preserves current execution identity.
        owner = participation(self)
        target = str(UUID(delivery_id)) if delivery_id else owner["delivery"]["id"]
        captured = owner if target == owner["delivery"]["id"] else await self.http("GET", "deliveries/" + target)
        delivery, request = captured["delivery"], captured["request"]
        if delivery["agent"] != self.config["agentId"] or request["authority"] != owner["request"]["authority"]:
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
        if target == owner["delivery"]["id"]:
            self.work_briefing = value
        saved(self.state / ("briefing-" + target + "-" + str(value["asOfSequence"]) + ".json"), value)
        if target == owner["delivery"]["id"] and getattr(self, "owner_briefing_delivery", None) == target:
            from .owner_briefing import publish
            await publish(self, value)
        return value

    async def _tool(self, method, params):
        def output(value, success=True):
            return {
                "success": success,
                "contentItems": [
                    {"type": "inputText", "text": json.dumps(value, default=str)}
                ],
            }

        owner = participation(self)
        if (not owner["nativeThread"] or not owner["nativeTurn"]
                or params.get("threadId", self.thread) != owner["nativeThread"]
                or params.get("turnId", owner["nativeTurn"]) != owner["nativeTurn"]):
            raise RuntimeError("Tool belongs to another captured native execution")
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
            "lax_native_edit_status",
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
            "requestId": owner["request"]["id"],
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
            elif name == "lax_native_edit_status":
                from .native_edit_status import inspect
                value = await inspect(self,arguments)
            elif name == "hollywood_withdraw_question":
                value = await self.attention.withdraw(str(UUID(arguments["attentionId"])),
                    arguments["reason"],operation=operation)
            elif name == "hollywood_ask":
                value = await self.attention.ask({**params, **arguments}, slot=call)
            elif name in ("hollywood_publish", "hollywood_request"):
                room, payload = message(self, name, arguments, operation)
                value = await self.http("POST", f"rooms/{room}/messages", payload)
                if name == "hollywood_request":
                    value = await index_accepted_delegation(
                        lambda path: self.http("GET", path),
                        LocatorLedger(self.state / "causal-locators-v2"),
                        owner, value,
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
                "hollywood_reconcile_pending_inputs",
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
                            owner, recovered,
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

