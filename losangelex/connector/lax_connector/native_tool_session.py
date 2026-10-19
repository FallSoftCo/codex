"""A purpose execution participant using the existing native tool core.

This read-capable integration does not grant native mutation authority. The
installed executor/effect integration must be present before that transport can
be enabled. No mutable legacy Connector.active or inferred binding is supplied.
"""
import json
from pathlib import Path

from .effects import Effects
from .native_tools import NativeTools
from .native_tool_catalog import TOOLS
from .roles import RoleContext
from .tool_execution import capture
from .workflow import READ_TOOLS

# Briefing for an older report records a scoped read receipt (POST). Retain its
# implementation in the shared core, but expose it only with the effect binding.
READ_NAMES = (READ_TOOLS - {"hollywood_briefing"}) | {
    "hollywood_rooms", "hollywood_read_room", "hollywood_room_info", "hollywood_agent_info",
}


def read_definitions():
    return [tool for tool in TOOLS if tool["name"] in READ_NAMES]


class NativeToolSession(NativeTools):
    """Explicit captured owner, native history and durable effect journal."""

    def __init__(self, *, accepted, scope, config, state, rpc, role, transport):
        self.config = config
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
        self.uncertain_tools = False
        self.goal_binding = None
        self.agent_binding = None
        self.publications = []
        self.work_briefing = None
        self.work_briefings = {}
        self.report_scope_briefings = {}
        self.report_scope_reads = {}

    def captured_execution(self):
        return json.loads(json.dumps(self._owner))

    async def _http(self, method, path, payload=None):
        if method != "GET":
            raise PermissionError("Native mutation transport requires installed executor integration")
        return await self._transport(method, path, payload)

    async def call(self, method, params):
        if method != "item/tool/call" or params.get("tool") not in READ_NAMES:
            raise PermissionError("Tool is not admitted by this native session")
        with self.effects.tool_scope(method, params):
            return await self._tool(method, params)
