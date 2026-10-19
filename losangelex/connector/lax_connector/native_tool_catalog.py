"""One declaration catalog for the shared executable native handlers."""
from .workflow import definitions as workflow_definitions

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
        "Ask the attributable human a necessary scoped question through Hollywood. Returns a durable pending receipt immediately; retain the unfinished outcome and continue other obligations or end this inference slice. The authenticated answer later arrives as primary input in your same context. Do not claim an answer or completed work from acceptance. Do not request secrets in chat.",
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


