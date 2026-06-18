use super::hollywood_config_for_session;
use super::resolve_coordination_target;
use crate::function_tool::FunctionCallError;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::tools::context::FunctionToolOutput;
use codex_protocol::ThreadId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use std::collections::BTreeMap;
use std::collections::HashSet;
use std::sync::Arc;

const MIN_COORDINATION_TASK_LIST_LIMIT: u32 = 1;
const DEFAULT_COORDINATION_TASK_LIST_LIMIT: u32 = 24;
const MAX_COORDINATION_TASK_LIST_LIMIT: u32 = 100;
const COMPACT_COORDINATION_DETAILS_PREVIEW_CHARS: usize = 320;

#[derive(Debug, Deserialize)]
pub(super) struct ListCoordinationTasksArgs {
    task_id: Option<String>,
    owner: Option<String>,
    creator: Option<String>,
    statuses: Option<Vec<String>>,
    room: Option<String>,
    view: Option<String>,
    limit: Option<u32>,
    #[serde(default)]
    include_history: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CoordinationTaskListView {
    Compact,
    Full,
    Subtree,
}

impl CoordinationTaskListView {
    fn parse(value: &str) -> Result<Self, String> {
        match value
            .trim()
            .to_ascii_lowercase()
            .replace(['-', ' '], "_")
            .as_str()
        {
            "compact" | "inbox" | "queue" => Ok(Self::Compact),
            "full" | "details" => Ok(Self::Full),
            "subtree" | "related" | "task_subtree" => Ok(Self::Subtree),
            other => Err(format!(
                "invalid list_coordination_tasks view `{other}`; expected compact, full, or subtree"
            )),
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::Compact => "compact",
            Self::Full => "full",
            Self::Subtree => "subtree",
        }
    }
}

#[derive(Debug, Serialize)]
struct CompactCoordinationTask {
    id: String,
    status: String,
    kind: String,
    summary: String,
    details_preview: Option<String>,
    creator_thread_id: String,
    owner_thread_id: Option<String>,
    owned_by_this_session: bool,
    created_by_this_session: bool,
    team_id: Option<String>,
    room: Option<String>,
    requested_capability: Option<String>,
    blocked_reason: Option<String>,
    dependency_task_ids: Vec<String>,
    blocked_dependency_task_ids: Vec<String>,
    created_at: i64,
    updated_at: i64,
    completed_at: Option<i64>,
    lease_expires_at: Option<i64>,
    needs_accept: bool,
    full_details_available: bool,
}

pub(super) async fn handle_list_coordination_tasks(
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    db: &Arc<codex_state::StateRuntime>,
    args: ListCoordinationTasksArgs,
) -> Result<FunctionToolOutput, FunctionCallError> {
    let view = match args.view.as_deref() {
        Some(view) => {
            CoordinationTaskListView::parse(view).map_err(FunctionCallError::RespondToModel)?
        }
        None if args.include_history => CoordinationTaskListView::Full,
        None => CoordinationTaskListView::Compact,
    };
    let limit = args
        .limit
        .unwrap_or(DEFAULT_COORDINATION_TASK_LIST_LIMIT)
        .clamp(
            MIN_COORDINATION_TASK_LIST_LIMIT,
            MAX_COORDINATION_TASK_LIST_LIMIT,
        ) as usize;
    let owner_thread_id = if let Some(owner) = args.owner.as_deref() {
        Some(resolve_coordination_target(session, turn, db, owner).await?)
    } else {
        None
    };
    let creator_thread_id = if let Some(creator) = args.creator.as_deref() {
        Some(resolve_coordination_target(session, turn, db, creator).await?)
    } else {
        None
    };
    let statuses = args
        .statuses
        .unwrap_or_default()
        .into_iter()
        .map(|status| super::parse_coordination_status(status.as_str()))
        .collect::<Result<Vec<_>, _>>()
        .map_err(FunctionCallError::RespondToModel)?;
    let room = match args.room {
        Some(room) => Some(room),
        None => hollywood_config_for_session(session, db)
            .await?
            .map(|config| config.room),
    };
    let task_id_filter = args.task_id.clone();
    let tasks = list_coordination_tasks_for_model(
        db,
        room.clone(),
        owner_thread_id,
        creator_thread_id,
        statuses,
        task_id_filter.as_deref(),
        view,
    )
    .await?;
    let total_matching = tasks.len();
    let returned_tasks = tasks.into_iter().take(limit).collect::<Vec<_>>();
    let content = if view == CoordinationTaskListView::Full {
        let mut content = json!({
            "view": view.as_str(),
            "room": room,
            "task_id": task_id_filter,
            "filter": {
                "returned": returned_tasks.len(),
                "total_matching": total_matching,
                "truncated": total_matching > returned_tasks.len(),
            },
            "counts": coordination_status_counts(
                returned_tasks.iter().map(|task| task.status.as_str())
            ),
            "tasks": returned_tasks,
        });
        if args.include_history {
            let task_ids = content["tasks"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|task| task["id"].as_str())
                .map(str::to_string)
                .collect::<Vec<_>>();
            let acts = db
                .list_coordination_acts(None)
                .await
                .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
            content["acts"] = json!(
                acts.into_iter()
                    .filter(|act| {
                        act.task_id
                            .as_ref()
                            .is_some_and(|task_id| task_ids.contains(task_id))
                    })
                    .collect::<Vec<_>>()
            );
        }
        content
    } else {
        let tasks = returned_tasks
            .iter()
            .map(|task| compact_coordination_task(task, session.thread_id()))
            .collect::<Vec<_>>();
        json!({
            "view": view.as_str(),
            "room": room,
            "task_id": task_id_filter,
            "filter": {
                "returned": tasks.len(),
                "total_matching": total_matching,
                "truncated": total_matching > tasks.len(),
            },
            "counts": coordination_status_counts(tasks.iter().map(|task| task.status.as_str())),
            "guidance": [
                "Use this compact durable task state before reading room messages.",
                "Use view `full` with task_id when exact details are required.",
                "Use hollywood_read with actionable_only/after_id only for direct message deltas, blockers, handoffs, or final answers."
            ],
            "tasks": tasks,
        })
    };
    Ok(FunctionToolOutput::from_text(
        serde_json::to_string_pretty(&content)
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?,
        Some(true),
    ))
}

async fn list_coordination_tasks_for_model(
    db: &Arc<codex_state::StateRuntime>,
    room: Option<String>,
    owner_thread_id: Option<ThreadId>,
    creator_thread_id: Option<ThreadId>,
    statuses: Vec<codex_state::CoordinationTaskStatus>,
    task_id: Option<&str>,
    view: CoordinationTaskListView,
) -> Result<Vec<codex_state::CoordinationTask>, FunctionCallError> {
    if let Some(task_id) = task_id {
        let root = db
            .get_coordination_task(task_id)
            .await
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?
            .ok_or_else(|| {
                FunctionCallError::RespondToModel(format!(
                    "coordination task {task_id} was not found"
                ))
            })?;
        if view != CoordinationTaskListView::Subtree {
            return Ok(vec![root]);
        }

        let mut tasks = db
            .list_coordination_tasks(codex_state::CoordinationTaskListFilter {
                owner_thread_id,
                creator_thread_id,
                room: root.room.clone().or(room),
                statuses,
            })
            .await
            .map_err(|err| FunctionCallError::Fatal(err.to_string()))?;
        if !tasks.iter().any(|task| task.id == root.id) {
            tasks.push(root.clone());
        }
        return Ok(coordination_task_subtree(root.id.as_str(), tasks));
    }

    db.list_coordination_tasks(codex_state::CoordinationTaskListFilter {
        owner_thread_id,
        creator_thread_id,
        room,
        statuses,
    })
    .await
    .map_err(|err| FunctionCallError::Fatal(err.to_string()))
}

fn coordination_task_subtree(
    root_task_id: &str,
    tasks: Vec<codex_state::CoordinationTask>,
) -> Vec<codex_state::CoordinationTask> {
    let mut included = HashSet::from([root_task_id.to_string()]);
    loop {
        let mut changed = false;
        for task in &tasks {
            let depends_on_included = task
                .dependency_task_ids
                .iter()
                .any(|task_id| included.contains(task_id));
            let included_depends_on_task = tasks
                .iter()
                .filter(|candidate| included.contains(&candidate.id))
                .any(|candidate| candidate.dependency_task_ids.contains(&task.id));
            if (depends_on_included || included_depends_on_task) && included.insert(task.id.clone())
            {
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }

    let mut root = Vec::new();
    let mut related = Vec::new();
    for task in tasks {
        if !included.contains(&task.id) {
            continue;
        }
        if task.id == root_task_id {
            root.push(task);
        } else {
            related.push(task);
        }
    }
    root.extend(related);
    root
}

fn compact_coordination_task(
    task: &codex_state::CoordinationTask,
    current_thread_id: ThreadId,
) -> CompactCoordinationTask {
    let current_thread_id = current_thread_id.to_string();
    let owned_by_this_session = task.owner_thread_id.as_deref() == Some(current_thread_id.as_str());
    CompactCoordinationTask {
        id: task.id.clone(),
        status: task.status.as_str().to_string(),
        kind: task.kind.as_str().to_string(),
        summary: task.summary.clone(),
        details_preview: compact_coordination_text_preview(
            task.details.as_str(),
            COMPACT_COORDINATION_DETAILS_PREVIEW_CHARS,
        ),
        creator_thread_id: task.creator_thread_id.clone(),
        owner_thread_id: task.owner_thread_id.clone(),
        owned_by_this_session,
        created_by_this_session: task.creator_thread_id == current_thread_id,
        team_id: task.team_id.clone(),
        room: task.room.clone(),
        requested_capability: task.requested_capability.clone(),
        blocked_reason: task.blocked_reason.clone(),
        dependency_task_ids: task.dependency_task_ids.clone(),
        blocked_dependency_task_ids: task.blocked_dependency_task_ids.clone(),
        created_at: task.created_at.timestamp(),
        updated_at: task.updated_at.timestamp(),
        completed_at: task.completed_at.map(|value| value.timestamp()),
        lease_expires_at: task.lease_expires_at.map(|value| value.timestamp()),
        needs_accept: owned_by_this_session
            && matches!(task.status, codex_state::CoordinationTaskStatus::Awarded),
        full_details_available: !task.details.trim().is_empty(),
    }
}

fn compact_coordination_text_preview(text: &str, max_chars: usize) -> Option<String> {
    let normalized = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if normalized.is_empty() {
        return None;
    }
    let total_chars = normalized.chars().count();
    if total_chars <= max_chars {
        return Some(normalized);
    }
    let mut preview = normalized.chars().take(max_chars).collect::<String>();
    preview.push_str("...");
    Some(preview)
}

fn coordination_status_counts<'a>(
    statuses: impl IntoIterator<Item = &'a str>,
) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::new();
    for status in statuses {
        *counts.entry(status.to_string()).or_insert(0) += 1;
    }
    counts
}
