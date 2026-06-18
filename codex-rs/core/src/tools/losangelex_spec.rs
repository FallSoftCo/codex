use crate::tools::context::ToolInvocation;
use crate::tools::handlers::CoordinationHandler;
use crate::tools::handlers::HollywoodReadHandler;
use crate::tools::handlers::HollywoodSendHandler;
use crate::tools::handlers::HollywoodStatusHandler;
use crate::tools::handlers::HollywoodTeamMemberUpdateHandler;
use crate::tools::handlers::HollywoodTeamStatusHandler;
use crate::tools::handlers::HollywoodTeamUpHandler;
use crate::tools::handlers::LosangelexTeamLaunchHandler;
use crate::tools::handlers::RestartClientHandler;
use crate::tools::registry::CoreToolRuntime;
use crate::tools::registry::ToolExecutor;
use codex_tools::JsonSchema;
use codex_tools::ResponsesApiTool;
use codex_tools::ToolExposure;
use codex_tools::ToolName;
use codex_tools::ToolSpec;
use serde_json::json;
use std::collections::BTreeMap;
use std::sync::Arc;

pub(crate) fn append_losangelex_tool_executors(
    executors: &mut Vec<Arc<dyn CoreToolRuntime>>,
    state_db_available: bool,
    hollywood_tools_available: bool,
) {
    executors.push(losangelex_tool(
        RestartClientHandler,
        create_restart_client_tool(),
    ));

    if state_db_available {
        executors.push(losangelex_tool(
            CoordinationHandler::new("coordination_act"),
            create_coordination_act_tool(),
        ));
        executors.push(losangelex_tool(
            CoordinationHandler::new("list_coordination_tasks"),
            create_list_coordination_tasks_tool(),
        ));
    }

    if hollywood_tools_available {
        executors.push(losangelex_tool(
            HollywoodStatusHandler,
            create_hollywood_status_tool(),
        ));
        executors.push(losangelex_tool(
            HollywoodReadHandler,
            create_hollywood_read_tool(),
        ));
        executors.push(losangelex_tool(
            LosangelexTeamLaunchHandler,
            create_losangelex_team_launch_tool(),
        ));
        executors.push(losangelex_tool(
            HollywoodSendHandler,
            create_hollywood_send_tool(state_db_available),
        ));
        executors.push(losangelex_tool(
            HollywoodTeamUpHandler,
            create_hollywood_team_up_tool(),
        ));
        executors.push(losangelex_tool(
            HollywoodTeamStatusHandler,
            create_hollywood_team_status_tool(),
        ));
        executors.push(losangelex_tool(
            HollywoodTeamMemberUpdateHandler,
            create_hollywood_team_member_update_tool(),
        ));
    }
}

fn losangelex_tool<T>(handler: T, spec: ToolSpec) -> Arc<dyn CoreToolRuntime>
where
    T: ToolExecutor<ToolInvocation> + 'static,
{
    Arc::new(LosangelexToolRuntime { handler, spec })
}

struct LosangelexToolRuntime<T> {
    handler: T,
    spec: ToolSpec,
}

impl<T> ToolExecutor<ToolInvocation> for LosangelexToolRuntime<T>
where
    T: ToolExecutor<ToolInvocation> + 'static,
{
    fn tool_name(&self) -> ToolName {
        self.handler.tool_name()
    }

    fn spec(&self) -> ToolSpec {
        self.spec.clone()
    }

    fn exposure(&self) -> ToolExposure {
        ToolExposure::DirectModelOnly
    }

    fn supports_parallel_tool_calls(&self) -> bool {
        self.handler.supports_parallel_tool_calls()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        self.handler.handle(invocation)
    }
}

impl<T> CoreToolRuntime for LosangelexToolRuntime<T> where T: ToolExecutor<ToolInvocation> + 'static {}

fn object_schema(
    properties: BTreeMap<String, JsonSchema>,
    required: Option<Vec<String>>,
) -> JsonSchema {
    JsonSchema::object(properties, required, Some(false.into()))
}

pub(crate) fn create_hollywood_status_tool() -> ToolSpec {
    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_status".to_string(),
        description: "Check whether Hollywood is configured and reachable for this session. Use this first when the user asks you to work with teammates, peers, or other existing agents so you can coordinate with existing attached Losangelex agents before considering `spawn_agent`.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(BTreeMap::new(), Some(Vec::new())),
        output_schema: None,
    })
}

pub(crate) fn create_coordination_act_tool() -> ToolSpec {
    let path_claim_schema = JsonSchema::object(
        BTreeMap::from([
            (
                "kind".to_string(),
                JsonSchema::string(Some("`file` or `directory`.".to_string())),
            ),
            (
                "path".to_string(),
                JsonSchema::string(Some(
                    "Absolute path or path relative to the current cwd.".to_string(),
                )),
            ),
        ]),
        Some(vec!["kind".to_string(), "path".to_string()]),
        Some(false.into()),
    );
    let properties = BTreeMap::from([
        (
            "action".to_string(),
            JsonSchema::string(Some(
                "Coordination act to record: `open_task`, `accept`, `done`, `cancel`, `handoff`, or `yield`."
                    .to_string(),
            )),
        ),
        (
            "task_id".to_string(),
            JsonSchema::string(Some(
                "Existing coordination task id for actions other than `open_task`.".to_string(),
            )),
        ),
        (
            "title".to_string(),
            JsonSchema::string(Some(
                "Task summary for `open_task`. Keep it short and concrete.".to_string(),
            )),
        ),
        (
            "details".to_string(),
            JsonSchema::string(Some("Optional longer task details or handoff notes.".to_string())),
        ),
        (
            "kind".to_string(),
            JsonSchema::string(Some(
                "Optional task kind for `open_task`: `general`, `implementation`, `review`, `investigation`, `qa`, or `handoff`."
                    .to_string(),
            )),
        ),
        (
            "owner".to_string(),
            JsonSchema::string(Some(
                "Optional target agent thread id or alias. Use this for directed awards or handoffs."
                    .to_string(),
            )),
        ),
        (
            "team_id".to_string(),
            JsonSchema::string(Some("Optional coordination team id to associate with the task.".to_string())),
        ),
        (
            "room".to_string(),
            JsonSchema::string(Some("Optional Hollywood room associated with the task. If omitted for non-general `open_task`, Losangelex derives a bounded `task/<repo>/<task>` room from the current Hollywood room and task title.".to_string())),
        ),
        (
            "capability".to_string(),
            JsonSchema::string(Some("Optional requested capability or specialty for the task.".to_string())),
        ),
        (
            "depends_on".to_string(),
            JsonSchema::array(
                JsonSchema::string(Some("Blocking coordination task id.".to_string())),
                Some("Optional dependency task ids that must be done before this task becomes actionable.".to_string()),
            ),
        ),
        (
            "summary".to_string(),
            JsonSchema::string(Some(
                "Concise durable act summary. Required for `done`, `cancel`, `handoff`, and `yield`; use a concrete result or reason, not placeholder text.".to_string(),
            )),
        ),
        (
            "notify_room".to_string(),
            JsonSchema::boolean(Some(
                "When true, also post a concise Hollywood room summary for visibility. Defaults to true."
                    .to_string(),
            )),
        ),
        (
            "claim_paths".to_string(),
            JsonSchema::array(
                path_claim_schema.clone(),
                Some("Optional exact ownership claims. For `accept`, these claims become active scope. For directed implementation `open_task`, they reserve exact scope for the awarded owner.".to_string()),
            ),
        ),
        (
            "release_paths".to_string(),
            JsonSchema::array(
                path_claim_schema,
                Some("Optional ownership claims to release while finishing, handing off, or yielding the task.".to_string()),
            ),
        ),
        (
            "lease_seconds".to_string(),
            JsonSchema::number(Some(
                "Optional active-lease duration for `accept`. Defaults to a long development-friendly lease."
                    .to_string(),
            )),
        ),
    ]);
    ToolSpec::Function(ResponsesApiTool {
        name: "coordination_act".to_string(),
        description: "Record a durable team-work commitment. Use this when natural-language coordination becomes an actual assignment, acceptance, completion, cancellation, handoff, or yield so Losangelex can persist the commitment, wake the right peer, and survive restart or rolling deploy.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(vec!["action".to_string()])),
        output_schema: None,
    })
}

pub(crate) fn create_list_coordination_tasks_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "task_id".to_string(),
            JsonSchema::string(Some(
                "Optional exact task id. Use with `view: \"full\"` for task-local details or `view: \"subtree\"` for dependency/dependent context.".to_string(),
            )),
        ),
        (
            "owner".to_string(),
            JsonSchema::string(Some("Optional owner agent thread id or alias filter.".to_string())),
        ),
        (
            "creator".to_string(),
            JsonSchema::string(Some("Optional creator agent thread id or alias filter.".to_string())),
        ),
        (
            "statuses".to_string(),
            JsonSchema::array(
                JsonSchema::string(Some("Task status filter.".to_string())),
                Some("Optional task statuses to include.".to_string()),
            ),
        ),
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional room filter. Defaults to the current attached Hollywood room when available."
                    .to_string(),
            )),
        ),
        (
            "include_history".to_string(),
            JsonSchema::boolean(Some(
                "When true, include durable coordination acts alongside the task list. This implies the heavier `full` view unless `view` is set explicitly.".to_string(),
            )),
        ),
        (
            "view".to_string(),
            JsonSchema::string_enum(
                vec![json!("compact"), json!("full"), json!("subtree")],
                Some(
                    "Result shape. `compact` is the default token-efficient work queue; `full` returns exact task details; `subtree` returns a compact task-local dependency/dependent slice for `task_id`.".to_string(),
                ),
            ),
        ),
        (
            "limit".to_string(),
            JsonSchema::integer(Some(
                "Maximum number of tasks to return. Defaults to 24 and caps at 100."
                    .to_string(),
            )),
        ),
    ]);
    ToolSpec::Function(ResponsesApiTool {
        name: "list_coordination_tasks".to_string(),
        description: "Inspect durable Losangelex coordination task state. Use this before `hollywood_read` for team coordination: the default compact view is a token-efficient work queue, `view:\"full\"` gives exact task details, and `view:\"subtree\"` gives task-local dependency/dependent context. When this session is attached to Hollywood, the current attached room is the default scope unless overridden.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(Vec::new())),
        output_schema: None,
    })
}

pub(crate) fn create_restart_client_tool() -> ToolSpec {
    let properties = BTreeMap::from([(
        "reason".to_string(),
        JsonSchema::string(Some(
            "Optional concise reason for the restart request, for example `rolling deploy`, `latest build available`, or `resume on new client generation`.".to_string(),
        )),
    )]);
    ToolSpec::Function(ResponsesApiTool {
        name: "restart_client".to_string(),
        description: "Request that the current Losangelex client exit and auto-resume this root thread through the launcher when available. This restarts the interactive client only; it does not create a new thread or subagent.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(Vec::new())),
        output_schema: None,
    })
}

pub(crate) fn create_hollywood_read_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional room to read from. Defaults to the configured Hollywood room."
                    .to_string(),
            )),
        ),
        (
            "after_id".to_string(),
            JsonSchema::number(Some(
                "Optional message id cursor. When provided, only newer messages are returned."
                    .to_string(),
            )),
        ),
        (
            "limit".to_string(),
            JsonSchema::number(Some(
                "Optional maximum number of messages to return. Defaults to 20, max 100."
                    .to_string(),
            )),
        ),
        (
            "actionable_only".to_string(),
            JsonSchema::boolean(Some(
                "When true, return only messages likely to require this agent's attention: direct recipients, @mentions, required replies, and broadcasts."
                    .to_string(),
            )),
        ),
        (
            "include_self".to_string(),
            JsonSchema::boolean(Some(
                "When true, include messages sent by this agent. Defaults to false so cursor reads avoid self-echo."
                    .to_string(),
            )),
        ),
    ]);
    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_read".to_string(),
        description: "Read message deltas and attached peer sessions from the configured Hollywood room. For coordination state, prefer `list_coordination_tasks` first; this read also returns a bounded `task_state` sidecar when available. Use cursor reads with `after_id` and `actionable_only` for direct mentions, blockers, handoffs, final answers, and other message-level deltas; the output includes `cursor.next_after_id` for the next read.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(Vec::new())),
        output_schema: None,
    })
}

pub(crate) fn create_losangelex_team_launch_tool() -> ToolSpec {
    let agent_schema = JsonSchema::object(
        BTreeMap::from([
            (
                "name".to_string(),
                JsonSchema::string(Some(
                    "Short human-readable peer name, for example `reviewer` or `qa`."
                        .to_string(),
                )),
            ),
            (
                "task".to_string(),
                JsonSchema::string(Some(
                    "Concrete initial assignment for this peer. Include exact scope, expected output, and coordination expectations."
                        .to_string(),
                )),
            ),
        ]),
        Some(vec!["name".to_string(), "task".to_string()]),
        Some(false.into()),
    );
    let properties = BTreeMap::from([
        (
            "agents".to_string(),
            JsonSchema::array(
                agent_schema,
                Some(
                    "Peers to launch. Keep this small and purposeful; at most eight peers are accepted."
                        .to_string(),
                ),
            ),
        ),
        (
            "workspace".to_string(),
            JsonSchema::string(Some(
                "Optional absolute workspace path. Defaults to this session's current local workspace."
                    .to_string(),
            )),
        ),
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional Hollywood room to attach peers to. Defaults to this session's configured room. For bounded parallel slices, prefer a `task/<repo>/<task>` room and keep the repo room observed for status and handoffs."
                    .to_string(),
            )),
        ),
        (
            "observed_rooms".to_string(),
            JsonSchema::array(
                JsonSchema::string(Some("Additional room to observe.".to_string())),
                Some(
                    "Optional observed rooms for launched peers. Defaults to this session's observed rooms."
                        .to_string(),
                ),
            ),
        ),
        (
            "wake_rooms".to_string(),
            JsonSchema::array(
                JsonSchema::string(Some("Room that may wake the peer.".to_string())),
                Some(
                    "Optional wake rooms for launched peers. Defaults to this session's wake rooms."
                        .to_string(),
                ),
            ),
        ),
        (
            "attention_mode".to_string(),
            JsonSchema::string(Some(
                "Optional Hollywood attention mode for peers: `focused`, `ambient`, or `broad`. Defaults to this session's mode."
                    .to_string(),
            )),
        ),
        (
            "model".to_string(),
            JsonSchema::string(Some(
                "Optional model override for launched peers. Omit to let app-server use its configured default."
                    .to_string(),
            )),
        ),
        (
            "model_provider".to_string(),
            JsonSchema::string(Some(
                "Optional model provider override for launched peers.".to_string(),
            )),
        ),
        (
            "start_turns".to_string(),
            JsonSchema::boolean(Some(
                "When false, create and attach peers without starting their initial task turns. Defaults to true."
                    .to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "losangelex_team_launch".to_string(),
        description: "Start app-server-hosted Losangelex peer sessions and attach them to the current Hollywood room. Use this when the user asks to form/start a Losangelex team, or when collaboration would materially help and no suitable attached peers already exist. Prefer this native tool over shelling out to `losangelex team`; it launches real Losangelex peer sessions, not Codex subagents.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(vec!["agents".to_string()])),
        output_schema: None,
    })
}

fn durable_coordination_tool_text(state_db_available: bool) -> &'static str {
    if state_db_available {
        "When the conversation becomes a real assignment, acceptance, handoff, dependency, or completion, pair the room update with `coordination_act` so the commitment is durable."
    } else {
        "This session does not currently expose durable coordination tools, so keep Hollywood ownership updates current and treat them as best-effort until durable coordination returns."
    }
}

pub(crate) fn create_hollywood_send_tool(state_db_available: bool) -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "text".to_string(),
            JsonSchema::string(Some(
                "Message body to send to Hollywood. Use @mentions when you need another agent's attention, and make ownership claims concrete with exact files, modules, directories, or narrow globs."
                    .to_string(),
            )),
        ),
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional room override. Defaults to the current attached Hollywood room. For bounded task slices, use a `task/<repo>/<task>` room instead of broad repo-room traffic.".to_string(),
            )),
        ),
        (
            "to".to_string(),
            JsonSchema::string(Some(
                "Optional direct recipient session id or alias. When omitted, the message goes to the room."
                    .to_string(),
            )),
        ),
        (
            "broadcast".to_string(),
            JsonSchema::boolean(Some(
                "When true, mark this as an explicit room-wide broadcast that should wake idle attached agents."
                    .to_string(),
            )),
        ),
        (
            "response_policy".to_string(),
            JsonSchema::string(Some(
                "Optional reply contract for the message: `required`, `optional`, or `none`."
                    .to_string(),
            )),
        ),
        (
            "message_type".to_string(),
            JsonSchema::string(Some(
                "Optional compact envelope type: `status`, `blocker`, `handoff`, or `final_answer`. When provided, Losangelex prefixes the body with `STATUS:`, `BLOCKER:`, `HANDOFF:`, or `FINAL_ANSWER:` for easier peer parsing."
                    .to_string(),
            )),
        ),
    ]);
    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_send".to_string(),
        description: format!(
            "Send a message to Hollywood as this agent. Use this to coordinate with other existing attached Losangelex agents through the local Hollywood room. {}",
            durable_coordination_tool_text(state_db_available)
        ),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(vec!["text".to_string()])),
        output_schema: None,
    })
}

pub(crate) fn create_hollywood_team_up_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "purpose".to_string(),
            JsonSchema::string(Some("Shared purpose for the team.".to_string())),
        ),
        (
            "targets".to_string(),
            JsonSchema::array(
                JsonSchema::string(Some("Target session id or alias.".to_string())),
                Some("Sessions to invite onto the team.".to_string()),
            ),
        ),
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional control room for the team record. Defaults to this session's configured Hollywood room."
                    .to_string(),
            )),
        ),
        (
            "task_room".to_string(),
            JsonSchema::string(Some(
                "Optional working room members should join after accepting. If omitted, Losangelex derives `task/<repo>/<task>` from the room and purpose."
                    .to_string(),
            )),
        ),
        (
            "team_id".to_string(),
            JsonSchema::string(Some("Optional explicit team id.".to_string())),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_team_up".to_string(),
        description: "Create a structured Hollywood collaboration with a purpose and invited member sessions. Roles are flexible; use member state updates for the current owner, reviewer, verifier, integrator, or handoff role instead of assuming a permanent leader.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(vec!["purpose".to_string(), "targets".to_string()])),
        output_schema: None,
    })
}

pub(crate) fn create_hollywood_team_status_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        (
            "room".to_string(),
            JsonSchema::string(Some(
                "Optional room to inspect. Defaults to the configured Hollywood room.".to_string(),
            )),
        ),
        (
            "limit".to_string(),
            JsonSchema::number(Some(
                "Maximum number of teams to return. Defaults to 20.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_team_status".to_string(),
        description: "Inspect structured Hollywood teams and member state for a room.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(Vec::new())),
        output_schema: None,
    })
}

pub(crate) fn create_hollywood_team_member_update_tool() -> ToolSpec {
    let properties = BTreeMap::from([
        ("team_id".to_string(), JsonSchema::string(Some("Team id to update.".to_string()))),
        (
            "session_id".to_string(),
            JsonSchema::string(Some(
                "Optional session id or alias to update. Defaults to this session.".to_string(),
            )),
        ),
        ("role".to_string(), JsonSchema::string(Some("Optional updated role.".to_string()))),
        ("state".to_string(), JsonSchema::string(Some("Optional updated team state.".to_string()))),
        (
            "joined_room".to_string(),
            JsonSchema::string(Some("Optional joined working room for this member.".to_string())),
        ),
        ("task".to_string(), JsonSchema::string(Some("Optional current task summary for this member.".to_string()))),
        (
            "scope".to_string(),
            JsonSchema::string(Some(
                "Optional scope or ownership summary for this member. Prefer exact files, modules, directories, or narrow globs over vague area names.".to_string(),
            )),
        ),
    ]);

    ToolSpec::Function(ResponsesApiTool {
        name: "hollywood_team_member_update".to_string(),
        description: "Update structured team-member state in Hollywood.".to_string(),
        strict: false,
        defer_loading: None,
        parameters: object_schema(properties, Some(vec!["team_id".to_string()])),
        output_schema: None,
    })
}
