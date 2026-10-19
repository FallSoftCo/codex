"""A purpose execution participant using the existing native tool core.

Purpose-native mutations use the accepted writer scope and an independently
observed executor. No legacy mutable Connector.active or synthetic goal binding
is supplied. The responder alone owns outward communication.
"""
import json
from pathlib import Path

from .effects import Effects
from .native_tools import NativeTools
from .native_tool_catalog import TOOLS
from .roles import RoleContext
from .tool_execution import capture
from .workflow import READ_TOOLS
from .attention import Attention, QUESTION, APPROVAL

# Briefing for an older report records a scoped read receipt (POST). Retain its
# implementation in the shared core, but expose it only with the effect binding.
READ_NAMES = (READ_TOOLS - {"hollywood_briefing"}) | {
    "hollywood_rooms", "hollywood_read_room", "hollywood_room_info", "hollywood_agent_info",
}


def read_definitions():
    return [tool for tool in TOOLS if tool["name"] in READ_NAMES]


def definitions(installed=False):
    if not installed:
        return read_definitions()
    return [t for t in TOOLS if t["name"] not in {
        "hollywood_publish","hollywood_request","hollywood_work_report_reconcile"}]


class NativeToolSession(NativeTools):
    """Explicit captured owner, native history and durable effect journal."""

    def __init__(self, *, accepted, scope, config, state, rpc, role, transport, finished=None, native_items=None):
        self.config = {**config,"codexHome":config["homes"]["writer"] if config.get("homes") else config.get("codexHome")}
        self.purpose_scope = dict(scope) if config.get("installedPurposeRuntime") else None
        if self.purpose_scope and (scope.get("schema")!="lax-execution-scope/v2" or not scope.get("executorId")):
            raise PermissionError("Installed purpose mutation needs an observed original executor")
        self.thread = scope["nativeThread"]
        self.context_id = scope["contextId"]
        self._owner = capture(accepted, thread=self.thread, turn=scope["nativeTurn"],
                              agent=config["agentId"], host=config["hostId"])
        d = self._owner["delivery"]
        expected = {"authorityId": d["authority"], "deliveryId": d["id"],
                    "sourceRequestId": d["event"], "claimId": d["claim_id"],
                    "generation": d["generation"], "agentId": d["agent"], "hostId": d["host"]}
        if any(scope.get(k) != v for k, v in expected.items()):
            raise PermissionError("Purpose execution receipt and original delivery differ")
        self.role_context = RoleContext.capture(role, config, accepted)
        if self.role_context.value["roleRevision"] != scope["roleRevision"]:
            raise PermissionError("Purpose execution role changed")
        self.state = Path(state)
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.rpc, self._transport = rpc, transport
        self.effects = Effects(self)
        self.attention = Attention(self)
        self.finished = finished
        self.native_items = native_items if native_items is not None else {}
        self.uncertain_tools = any(
            json.loads(p.read_text()).get("state")!="completed" for p in self.state.glob("tool-*.json"))
        self.goal_binding = None
        self.agent_binding = None
        self.publications = []
        self.owner_briefing_delivery = d["id"] if self.config.get("nativeCollaborationChannel") else None
        self.work_briefing = None
        self.work_briefings = {}
        self.report_scope_briefings = {}
        self.report_scope_reads = {}

    def captured_execution(self):
        return json.loads(json.dumps(self._owner))

    async def _http(self, method, path, payload=None):
        source=None
        if method!="GET":
            if not self.purpose_scope:
                raise PermissionError("Native mutation transport requires installed executor integration")
            current=self.effects.current.get()
            if current:
                from .effects import native_source
                source=native_source(current["scope"],purpose=self.purpose_scope)
            elif not (path=="attention" or path.startswith("attention/")):
                raise PermissionError("Original native tool callback required")
        return await self._transport(method,path,payload,native_source=source) if self.purpose_scope else await self._transport(method,path,payload)

    async def call(self, method, params):
        allowed={t["name"] for t in definitions(bool(self.purpose_scope))}
        if not (method=="item/tool/call" and params.get("tool") in allowed
                or self.purpose_scope and method in QUESTION+APPROVAL):
            raise PermissionError("Tool is not admitted by this native session")
        with self.effects.tool_scope(method, params):
            return await self._tool(method, params)
