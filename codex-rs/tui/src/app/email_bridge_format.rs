use super::thread_events::ThreadBufferedEvent;
use crate::app_server_session::ThreadSessionState;
use codex_app_server_protocol::CollabAgentTool;
use codex_app_server_protocol::CollabAgentToolCallStatus;
use codex_app_server_protocol::CommandExecutionStatus;
use codex_app_server_protocol::DynamicToolCallStatus;
use codex_app_server_protocol::FileUpdateChange;
use codex_app_server_protocol::McpToolCallStatus;
use codex_app_server_protocol::PatchApplyStatus;
use codex_app_server_protocol::PatchChangeKind;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput as AppServerUserInput;
use codex_protocol::ThreadId;
use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;

const MAX_MESSAGE_SUMMARY_CHARS: usize = 500;
const MAX_ACTIVITY_LINES: usize = 6;
const MAX_ACTIVITY_CHARS: usize = 180;
const MAX_COMMAND_CHARS: usize = 120;
const MAX_QUERY_CHARS: usize = 120;
const MAX_PATHS_IN_SUMMARY: usize = 3;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct EmailSessionContext {
    pub(super) thread_name: Option<String>,
    pub(super) model: String,
    pub(super) model_provider_id: String,
    pub(super) cwd: PathBuf,
    pub(super) rollout_path: Option<PathBuf>,
    pub(super) forked_from_id: Option<ThreadId>,
    pub(super) fork_parent_title: Option<String>,
}

impl From<ThreadSessionState> for EmailSessionContext {
    fn from(value: ThreadSessionState) -> Self {
        Self {
            thread_name: value.thread_name,
            model: value.model,
            model_provider_id: value.model_provider_id,
            cwd: value.cwd.to_path_buf(),
            rollout_path: value.rollout_path,
            forked_from_id: value.forked_from_id,
            fork_parent_title: value.fork_parent_title,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct EmailThreadSnapshot {
    pub(super) thread_id: ThreadId,
    pub(super) thread_label: String,
    pub(super) session: Option<EmailSessionContext>,
    pub(super) active_turn_id: Option<String>,
    pub(super) latest_completed_turn_id: Option<String>,
    pub(super) recent_user_message: Option<String>,
    pub(super) recent_agent_message: Option<String>,
    pub(super) recent_agent_email_body: Option<String>,
    pub(super) current_activity: Vec<String>,
    pub(super) latest_completed_activity: Vec<String>,
}

#[derive(Debug, Clone)]
struct BufferedThreadItem {
    turn_id: String,
    item: ThreadItem,
    completed: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RecentMessageKind {
    UserSummary,
    AgentSummary,
    AgentEmailBody,
}

impl EmailThreadSnapshot {
    pub(super) fn from_state(
        thread_id: ThreadId,
        thread_label: String,
        session: Option<ThreadSessionState>,
        turns: &[Turn],
        buffered_events: &[ThreadBufferedEvent],
        active_turn_id: Option<String>,
    ) -> Self {
        let buffered_items = buffered_thread_items(buffered_events);
        let latest_completed_turn_id = latest_completed_turn_id(buffered_events, turns);
        let recent_user_message =
            recent_message_text(&buffered_items, turns, RecentMessageKind::UserSummary);
        let recent_agent_message =
            recent_message_text(&buffered_items, turns, RecentMessageKind::AgentSummary);
        let recent_agent_email_body =
            recent_message_text(&buffered_items, turns, RecentMessageKind::AgentEmailBody);
        let current_activity = active_turn_id
            .as_deref()
            .map(|turn_id| {
                activity_for_turn(
                    turn_id,
                    turns,
                    &buffered_items,
                    /*include_started*/ true,
                )
            })
            .unwrap_or_default();
        let latest_completed_activity = latest_completed_turn_id
            .as_deref()
            .map(|turn_id| {
                activity_for_turn(
                    turn_id,
                    turns,
                    &buffered_items,
                    /*include_started*/ false,
                )
            })
            .unwrap_or_default();

        Self {
            thread_id,
            thread_label,
            session: session.map(Into::into),
            active_turn_id,
            latest_completed_turn_id,
            recent_user_message,
            recent_agent_message,
            recent_agent_email_body,
            current_activity,
            latest_completed_activity,
        }
    }
}

pub(super) fn format_completion_email(
    snapshot: &EmailThreadSnapshot,
    subject_prefix: &str,
    token: &str,
) -> (String, String) {
    let subject = format!(
        "{} {} completed work [lx:{}]",
        subject_prefix,
        subject_context(snapshot),
        token
    );
    let mut lines = Vec::new();
    push_completion_message(&mut lines, snapshot.recent_agent_email_body.as_deref());
    push_message_section(
        &mut lines,
        "Recent user request",
        snapshot.recent_user_message.as_deref(),
    );
    push_list_section(
        &mut lines,
        "Latest completed activity",
        snapshot
            .latest_completed_activity
            .iter()
            .map(String::as_str),
    );
    push_context_section(
        &mut lines,
        snapshot,
        "idle",
        snapshot.latest_completed_turn_id.as_deref(),
    );
    push_reply_instructions(&mut lines, token);
    (subject, lines.join("\n"))
}

pub(super) fn format_request_user_input_email(
    snapshot: &EmailThreadSnapshot,
    subject_prefix: &str,
    token: &str,
    prompt: &str,
) -> (String, String) {
    let subject = format!(
        "{} {} needs attention [lx:{}]",
        subject_prefix,
        subject_context(snapshot),
        token
    );
    let mut lines = header_lines(
        snapshot,
        "waiting on structured input",
        snapshot.active_turn_id.as_deref(),
    );
    push_message_section(
        &mut lines,
        "Recent user request",
        snapshot.recent_user_message.as_deref(),
    );
    push_message_section(
        &mut lines,
        "Latest agent response",
        snapshot.recent_agent_message.as_deref(),
    );
    push_verbatim_section(&mut lines, "Structured input needed", prompt);
    push_list_section(
        &mut lines,
        "Current activity",
        snapshot.current_activity.iter().map(String::as_str),
    );
    lines.push(
        "Email replies do not resolve structured prompts yet. Open Losangelex locally to answer this request directly.".to_string(),
    );
    push_reply_instructions(&mut lines, token);
    (subject, lines.join("\n"))
}

pub(super) fn format_reply_rejected_email(
    snapshot: &EmailThreadSnapshot,
    subject_prefix: &str,
    token: &str,
    reason: &str,
) -> (String, String) {
    let subject = format!(
        "{} {} reply rejected [lx:{}]",
        subject_prefix,
        subject_context(snapshot),
        token
    );
    let mut lines = header_lines(
        snapshot,
        "reply rejected",
        snapshot.active_turn_id.as_deref(),
    );
    lines.push(format!("Reason: {}", sanitize_inline_text(reason)));
    push_message_section(
        &mut lines,
        "Recent user request",
        snapshot.recent_user_message.as_deref(),
    );
    push_message_section(
        &mut lines,
        "Latest agent response",
        snapshot.recent_agent_message.as_deref(),
    );
    push_list_section(
        &mut lines,
        "Current activity",
        snapshot.current_activity.iter().map(String::as_str),
    );
    push_list_section(
        &mut lines,
        "Latest completed activity",
        snapshot
            .latest_completed_activity
            .iter()
            .map(String::as_str),
    );
    lines.push(
        "Open Losangelex locally to inspect the thread, or reply again with updated instructions."
            .to_string(),
    );
    push_reply_instructions(&mut lines, token);
    (subject, lines.join("\n"))
}

pub(super) fn format_status_email(
    snapshot: &EmailThreadSnapshot,
    subject_prefix: &str,
    token: &str,
) -> (String, String) {
    let status = if snapshot.active_turn_id.is_some() {
        "active"
    } else {
        "idle"
    };
    let turn_id = snapshot
        .active_turn_id
        .as_deref()
        .or(snapshot.latest_completed_turn_id.as_deref());
    let subject = format!(
        "{} {} status [lx:{}]",
        subject_prefix,
        subject_context(snapshot),
        token
    );
    let mut lines = header_lines(snapshot, status, turn_id);
    push_message_section(
        &mut lines,
        "Recent user request",
        snapshot.recent_user_message.as_deref(),
    );
    push_message_section(
        &mut lines,
        "Latest agent response",
        snapshot.recent_agent_message.as_deref(),
    );
    push_list_section(
        &mut lines,
        "Current activity",
        snapshot.current_activity.iter().map(String::as_str),
    );
    push_list_section(
        &mut lines,
        "Latest completed activity",
        snapshot
            .latest_completed_activity
            .iter()
            .map(String::as_str),
    );
    push_reply_instructions(&mut lines, token);
    (subject, lines.join("\n"))
}

fn header_lines(
    snapshot: &EmailThreadSnapshot,
    status: &str,
    focus_turn_id: Option<&str>,
) -> Vec<String> {
    let mut lines = context_lines(snapshot, status, focus_turn_id);
    lines.push(String::new());
    lines
}

fn context_lines(
    snapshot: &EmailThreadSnapshot,
    status: &str,
    focus_turn_id: Option<&str>,
) -> Vec<String> {
    let mut lines = vec![
        format!("Thread: {}", snapshot.thread_label),
        format!("Thread ID: {}", snapshot.thread_id),
        format!("Status: {status}"),
    ];
    if let Some(turn_id) = focus_turn_id {
        lines.push(format!("Turn ID: {turn_id}"));
    }
    if let Some(session) = snapshot.session.as_ref() {
        lines.push(format!("Working directory: {}", session.cwd.display()));
        if !session.model.is_empty() || !session.model_provider_id.is_empty() {
            lines.push(format!(
                "Model: {}{}",
                session.model,
                if session.model_provider_id.is_empty() {
                    String::new()
                } else {
                    format!(" ({})", session.model_provider_id)
                }
            ));
        }
        if let Some(thread_name) = session.thread_name.as_deref()
            && thread_name != snapshot.thread_label
        {
            lines.push(format!(
                "Thread name: {}",
                sanitize_inline_text(thread_name)
            ));
        }
        if let Some(parent_title) = session.fork_parent_title.as_deref() {
            let parent_id = session
                .forked_from_id
                .map(|thread_id| thread_id.to_string())
                .unwrap_or_else(|| "unknown".to_string());
            lines.push(format!(
                "Forked from: {} ({parent_id})",
                sanitize_inline_text(parent_title)
            ));
        }
        if let Some(rollout_path) = session.rollout_path.as_ref() {
            lines.push(format!("Rollout path: {}", rollout_path.display()));
        }
    }
    lines
}

fn push_completion_message(lines: &mut Vec<String>, message: Option<&str>) {
    if let Some(message) = message.filter(|message| !message.trim().is_empty()) {
        lines.extend(message.lines().map(ToOwned::to_owned));
    } else {
        lines.push("Losangelex completed work without a final assistant message.".to_string());
    }
    lines.push(String::new());
}

fn push_context_section(
    lines: &mut Vec<String>,
    snapshot: &EmailThreadSnapshot,
    status: &str,
    focus_turn_id: Option<&str>,
) {
    let context = context_lines(snapshot, status, focus_turn_id);
    push_list_section(lines, "Thread context", context.iter().map(String::as_str));
}

fn push_reply_instructions(lines: &mut Vec<String>, token: &str) {
    push_list_section(
        lines,
        "Reply commands",
        [
            "Reply with plain text to continue this thread.",
            "Reply with `@losangelex continue ...` to make the instruction explicit.",
            "Reply with `status` for a refreshed status email.",
            "Reply with `stop` to interrupt the active turn.",
        ],
    );
    lines.push(format!("Reply token: {token}"));
}

fn push_message_section(lines: &mut Vec<String>, title: &str, message: Option<&str>) {
    let Some(message) = message.filter(|message| !message.is_empty()) else {
        return;
    };
    lines.push(format!("{title}:"));
    lines.push(truncate_text(message, MAX_MESSAGE_SUMMARY_CHARS));
    lines.push(String::new());
}

fn push_verbatim_section(lines: &mut Vec<String>, title: &str, body: &str) {
    if body.trim().is_empty() {
        return;
    }
    lines.push(format!("{title}:"));
    lines.extend(body.lines().map(ToOwned::to_owned));
    lines.push(String::new());
}

fn push_list_section<'a>(
    lines: &mut Vec<String>,
    title: &str,
    values: impl IntoIterator<Item = &'a str>,
) {
    let values = values
        .into_iter()
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>();
    if values.is_empty() {
        return;
    }
    lines.push(format!("{title}:"));
    lines.extend(values.into_iter().map(|value| format!("- {value}")));
    lines.push(String::new());
}

fn subject_context(snapshot: &EmailThreadSnapshot) -> String {
    if let Some(session) = snapshot.session.as_ref() {
        let cwd = path_tail(session.cwd.as_path());
        format!("{cwd} / {}", snapshot.thread_label)
    } else {
        snapshot.thread_label.clone()
    }
}

fn latest_completed_turn_id(
    buffered_events: &[ThreadBufferedEvent],
    turns: &[Turn],
) -> Option<String> {
    buffered_events
        .iter()
        .rev()
        .find_map(|event| match event {
            ThreadBufferedEvent::Notification(ServerNotification::TurnCompleted(notification)) => {
                Some(notification.turn.id.clone())
            }
            ThreadBufferedEvent::Notification(_)
            | ThreadBufferedEvent::Request(_)
            | ThreadBufferedEvent::HistoryEntryResponse(_)
            | ThreadBufferedEvent::FeedbackSubmission(_) => None,
        })
        .or_else(|| {
            turns
                .iter()
                .rev()
                .find(|turn| {
                    !matches!(turn.status, TurnStatus::InProgress) && !turn.items.is_empty()
                })
                .map(|turn| turn.id.clone())
        })
}

fn buffered_thread_items(buffered_events: &[ThreadBufferedEvent]) -> Vec<BufferedThreadItem> {
    buffered_events
        .iter()
        .filter_map(|event| match event {
            ThreadBufferedEvent::Notification(ServerNotification::ItemStarted(notification)) => {
                Some(BufferedThreadItem {
                    turn_id: notification.turn_id.clone(),
                    item: notification.item.clone(),
                    completed: false,
                })
            }
            ThreadBufferedEvent::Notification(ServerNotification::ItemCompleted(notification)) => {
                Some(BufferedThreadItem {
                    turn_id: notification.turn_id.clone(),
                    item: notification.item.clone(),
                    completed: true,
                })
            }
            ThreadBufferedEvent::Notification(_)
            | ThreadBufferedEvent::Request(_)
            | ThreadBufferedEvent::HistoryEntryResponse(_)
            | ThreadBufferedEvent::FeedbackSubmission(_) => None,
        })
        .collect()
}

fn activity_for_turn(
    turn_id: &str,
    turns: &[Turn],
    buffered_items: &[BufferedThreadItem],
    include_started: bool,
) -> Vec<String> {
    let mut ordered_ids = Vec::new();
    let mut latest_items = HashMap::new();
    for buffered in buffered_items
        .iter()
        .filter(|buffered| buffered.turn_id == turn_id)
    {
        if !include_started && !buffered.completed {
            continue;
        }
        let item_id = buffered.item.id().to_string();
        if !latest_items.contains_key(&item_id) {
            ordered_ids.push(item_id.clone());
        }
        if buffered.completed || !latest_items.contains_key(&item_id) {
            latest_items.insert(item_id, buffered.item.clone());
        }
    }

    let mut lines = ordered_ids
        .into_iter()
        .filter_map(|item_id| latest_items.remove(&item_id))
        .filter_map(|item| summarize_thread_item(&item))
        .take(MAX_ACTIVITY_LINES)
        .collect::<Vec<_>>();
    if !lines.is_empty() {
        return lines;
    }

    if let Some(turn) = turns.iter().find(|turn| turn.id == turn_id) {
        lines.extend(
            turn.items
                .iter()
                .filter_map(summarize_thread_item)
                .take(MAX_ACTIVITY_LINES),
        );
    }
    lines
}

fn recent_message_text(
    buffered_items: &[BufferedThreadItem],
    turns: &[Turn],
    kind: RecentMessageKind,
) -> Option<String> {
    buffered_items
        .iter()
        .rev()
        .find_map(|buffered| message_text_from_item(&buffered.item, kind))
        .or_else(|| {
            turns
                .iter()
                .rev()
                .flat_map(|turn| turn.items.iter().rev())
                .find_map(|item| message_text_from_item(item, kind))
        })
}

fn message_text_from_item(item: &ThreadItem, kind: RecentMessageKind) -> Option<String> {
    match item {
        ThreadItem::UserMessage { content, .. } if kind == RecentMessageKind::UserSummary => {
            let text = summarize_user_inputs(content);
            (!text.is_empty()).then_some(text)
        }
        ThreadItem::AgentMessage { text, .. } if kind == RecentMessageKind::AgentSummary => {
            let text = truncate_text(text, MAX_MESSAGE_SUMMARY_CHARS);
            (!text.is_empty()).then_some(text)
        }
        ThreadItem::AgentMessage { text, .. } if kind == RecentMessageKind::AgentEmailBody => {
            let text = sanitize_email_body_text(text);
            (!text.is_empty()).then_some(text)
        }
        ThreadItem::UserMessage { .. }
        | ThreadItem::HookPrompt { .. }
        | ThreadItem::AgentMessage { .. }
        | ThreadItem::Plan { .. }
        | ThreadItem::Reasoning { .. }
        | ThreadItem::CommandExecution { .. }
        | ThreadItem::FileChange { .. }
        | ThreadItem::McpToolCall { .. }
        | ThreadItem::DynamicToolCall { .. }
        | ThreadItem::CollabAgentToolCall { .. }
        | ThreadItem::WebSearch { .. }
        | ThreadItem::ImageView { .. }
        | ThreadItem::ImageGeneration { .. }
        | ThreadItem::EnteredReviewMode { .. }
        | ThreadItem::ExitedReviewMode { .. }
        | ThreadItem::ContextCompaction { .. } => None,
    }
}

fn summarize_thread_item(item: &ThreadItem) -> Option<String> {
    match item {
        ThreadItem::UserMessage { .. }
        | ThreadItem::AgentMessage { .. }
        | ThreadItem::HookPrompt { .. } => None,
        ThreadItem::Plan { text, .. } => {
            Some(format!("Plan: {}", truncate_text(text, MAX_ACTIVITY_CHARS)))
        }
        ThreadItem::Reasoning {
            summary, content, ..
        } => {
            let text = summary
                .iter()
                .chain(content.iter())
                .find(|text| !text.trim().is_empty())
                .map(|text| truncate_text(text, MAX_ACTIVITY_CHARS));
            text.map(|text| format!("Reasoning: {text}"))
        }
        ThreadItem::CommandExecution {
            command,
            cwd,
            status,
            exit_code,
            duration_ms,
            aggregated_output,
            ..
        } => {
            let mut details = vec![command_status_label(status).to_string()];
            if let Some(exit_code) = exit_code {
                details.push(format!("exit {exit_code}"));
            }
            if let Some(duration_ms) = duration_ms {
                details.push(format_duration_ms(*duration_ms));
            }
            let mut line = format!(
                "Command {} in {} ({})",
                truncate_code(command, MAX_COMMAND_CHARS),
                path_tail(cwd.as_path()),
                details.join(", ")
            );
            if matches!(
                status,
                CommandExecutionStatus::Failed | CommandExecutionStatus::Declined
            ) && let Some(output) = aggregated_output.as_deref()
            {
                let output = truncate_text(output, MAX_ACTIVITY_CHARS);
                if !output.is_empty() {
                    line.push_str(format!(": {output}").as_str());
                }
            }
            Some(line)
        }
        ThreadItem::FileChange {
            changes, status, ..
        } => Some(format!(
            "File changes ({}){}",
            patch_status_label(status),
            summarize_file_changes(changes)
        )),
        ThreadItem::McpToolCall {
            server,
            tool,
            status,
            ..
        } => Some(format!(
            "MCP {server}/{tool} ({})",
            mcp_status_label(status)
        )),
        ThreadItem::DynamicToolCall {
            namespace,
            tool,
            status,
            success,
            ..
        } => {
            let tool_label = namespace
                .as_deref()
                .map(|namespace| format!("{namespace}/{tool}"))
                .unwrap_or_else(|| tool.clone());
            let outcome = success.map(|success| if success { "success" } else { "error" });
            Some(match outcome {
                Some(outcome) => format!(
                    "Tool {tool_label} ({}, {outcome})",
                    dynamic_tool_status_label(status)
                ),
                None => format!("Tool {tool_label} ({})", dynamic_tool_status_label(status)),
            })
        }
        ThreadItem::CollabAgentToolCall {
            tool,
            status,
            receiver_thread_ids,
            ..
        } => Some(format!(
            "Peer action {} -> {} agent(s) ({})",
            collab_tool_label(tool),
            receiver_thread_ids.len(),
            collab_tool_status_label(status)
        )),
        ThreadItem::WebSearch { query, .. } => Some(format!(
            "Web search: {}",
            truncate_text(query, MAX_QUERY_CHARS)
        )),
        ThreadItem::ImageView { path, .. } => {
            Some(format!("Viewed image: {}", path_tail(path.as_path())))
        }
        ThreadItem::ImageGeneration {
            status,
            revised_prompt,
            result,
            ..
        } => {
            let detail = revised_prompt
                .as_deref()
                .filter(|prompt| !prompt.trim().is_empty())
                .unwrap_or(result.as_str());
            Some(format!(
                "Image generation ({}): {}",
                sanitize_inline_text(status),
                truncate_text(detail, MAX_ACTIVITY_CHARS)
            ))
        }
        ThreadItem::EnteredReviewMode { review, .. } => Some(format!(
            "Entered review mode: {}",
            truncate_text(review, MAX_ACTIVITY_CHARS)
        )),
        ThreadItem::ExitedReviewMode { review, .. } => Some(format!(
            "Exited review mode: {}",
            truncate_text(review, MAX_ACTIVITY_CHARS)
        )),
        ThreadItem::ContextCompaction { .. } => Some("Context compacted.".to_string()),
    }
}

fn summarize_file_changes(changes: &[FileUpdateChange]) -> String {
    if changes.is_empty() {
        return ".".to_string();
    }
    let mut parts = changes
        .iter()
        .take(MAX_PATHS_IN_SUMMARY)
        .map(|change| match &change.kind {
            PatchChangeKind::Add => format!("added {}", sanitize_inline_text(change.path.as_str())),
            PatchChangeKind::Delete => {
                format!("deleted {}", sanitize_inline_text(change.path.as_str()))
            }
            PatchChangeKind::Update { move_path } => {
                if let Some(move_path) = move_path.as_ref() {
                    format!(
                        "updated {} -> {}",
                        sanitize_inline_text(change.path.as_str()),
                        sanitize_inline_text(move_path.display().to_string().as_str())
                    )
                } else {
                    format!("updated {}", sanitize_inline_text(change.path.as_str()))
                }
            }
        })
        .collect::<Vec<_>>();
    if changes.len() > MAX_PATHS_IN_SUMMARY {
        parts.push(format!("+{} more", changes.len() - MAX_PATHS_IN_SUMMARY));
    }
    format!(": {}", parts.join(", "))
}

fn summarize_user_inputs(content: &[AppServerUserInput]) -> String {
    let mut parts = Vec::new();
    for item in content {
        match item {
            AppServerUserInput::Text { text, .. } => {
                let text = sanitize_multiline_text(text);
                if !text.is_empty() {
                    parts.push(text);
                }
            }
            AppServerUserInput::Image { url } => parts.push(format!("[image: {url}]")),
            AppServerUserInput::LocalImage { path } => {
                parts.push(format!("[local image: {}]", path.display()));
            }
            AppServerUserInput::Skill { name, .. } => parts.push(format!("[skill: {name}]")),
            AppServerUserInput::Mention { name, .. } => parts.push(format!("[mention: {name}]")),
        }
    }
    truncate_text(parts.join(" ").as_str(), MAX_MESSAGE_SUMMARY_CHARS)
}

fn truncate_code(text: &str, max_chars: usize) -> String {
    format!("`{}`", truncate_text(text, max_chars))
}

fn truncate_text(text: &str, max_chars: usize) -> String {
    let sanitized = sanitize_multiline_text(text);
    let char_count = sanitized.chars().count();
    if char_count <= max_chars {
        return sanitized;
    }
    sanitized
        .chars()
        .take(max_chars.saturating_sub(1))
        .collect::<String>()
        + "…"
}

fn sanitize_email_body_text(text: &str) -> String {
    let mut lines = text.lines().map(str::trim_end).collect::<Vec<_>>();
    while lines.first().is_some_and(|line| line.trim().is_empty()) {
        lines.remove(0);
    }
    while lines.last().is_some_and(|line| line.trim().is_empty()) {
        lines.pop();
    }

    let mut sanitized = Vec::new();
    let mut previous_blank = false;
    for line in lines {
        let is_blank = line.trim().is_empty();
        if is_blank {
            if !previous_blank {
                sanitized.push(String::new());
            }
        } else {
            sanitized.push(line.to_string());
        }
        previous_blank = is_blank;
    }

    sanitized.join("\n")
}

fn sanitize_multiline_text(text: &str) -> String {
    text.lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

fn sanitize_inline_text(text: &str) -> String {
    sanitize_multiline_text(text)
}

fn path_tail(path: &Path) -> String {
    path.file_name()
        .and_then(|segment| segment.to_str())
        .filter(|segment| !segment.is_empty())
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| path.display().to_string())
}

fn command_status_label(status: &CommandExecutionStatus) -> &'static str {
    match status {
        CommandExecutionStatus::InProgress => "in progress",
        CommandExecutionStatus::Completed => "completed",
        CommandExecutionStatus::Failed => "failed",
        CommandExecutionStatus::Declined => "declined",
    }
}

fn patch_status_label(status: &PatchApplyStatus) -> &'static str {
    match status {
        PatchApplyStatus::InProgress => "in progress",
        PatchApplyStatus::Completed => "completed",
        PatchApplyStatus::Failed => "failed",
        PatchApplyStatus::Declined => "declined",
    }
}

fn mcp_status_label(status: &McpToolCallStatus) -> &'static str {
    match status {
        McpToolCallStatus::InProgress => "in progress",
        McpToolCallStatus::Completed => "completed",
        McpToolCallStatus::Failed => "failed",
    }
}

fn dynamic_tool_status_label(status: &DynamicToolCallStatus) -> &'static str {
    match status {
        DynamicToolCallStatus::InProgress => "in progress",
        DynamicToolCallStatus::Completed => "completed",
        DynamicToolCallStatus::Failed => "failed",
    }
}

fn collab_tool_status_label(status: &CollabAgentToolCallStatus) -> &'static str {
    match status {
        CollabAgentToolCallStatus::InProgress => "in progress",
        CollabAgentToolCallStatus::Completed => "completed",
        CollabAgentToolCallStatus::Failed => "failed",
    }
}

fn collab_tool_label(tool: &CollabAgentTool) -> &'static str {
    match tool {
        CollabAgentTool::SpawnAgent => "spawn_agent",
        CollabAgentTool::SendInput => "send_input",
        CollabAgentTool::ResumeAgent => "resume_agent",
        CollabAgentTool::Wait => "wait_agent",
        CollabAgentTool::CloseAgent => "close_agent",
    }
}

fn format_duration_ms(duration_ms: i64) -> String {
    if duration_ms >= 1000 {
        format!("{:.1}s", duration_ms as f64 / 1000.0)
    } else {
        format!("{duration_ms}ms")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_app_server_protocol::CommandExecutionStatus;
    use codex_app_server_protocol::FileUpdateChange;
    use codex_app_server_protocol::ItemCompletedNotification;
    use codex_app_server_protocol::PatchApplyStatus;
    use codex_app_server_protocol::ServerNotification;
    use codex_app_server_protocol::ThreadItem;
    use codex_app_server_protocol::Turn;
    use codex_app_server_protocol::TurnStatus;
    use codex_protocol::protocol::AskForApproval;
    use codex_protocol::protocol::SandboxPolicy;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use pretty_assertions::assert_eq;

    fn test_thread_id() -> ThreadId {
        ThreadId::from_string("019dad46-de5d-79a2-a8e1-c3592ac34db1").expect("thread id")
    }

    fn test_session() -> ThreadSessionState {
        ThreadSessionState {
            thread_id: test_thread_id(),
            forked_from_id: None,
            fork_parent_title: Some("Parent agent".to_string()),
            thread_name: Some("Release agent".to_string()),
            model: "gpt-5.4".to_string(),
            model_provider_id: "openai".to_string(),
            service_tier: None,
            approval_policy: AskForApproval::OnRequest,
            approvals_reviewer: codex_protocol::config_types::ApprovalsReviewer::User,
            sandbox_policy: SandboxPolicy::new_read_only_policy(),
            cwd: AbsolutePathBuf::try_from(PathBuf::from("/home/ai/Development/ozzz"))
                .expect("cwd"),
            instruction_source_paths: Vec::new(),
            reasoning_effort: None,
            history_log_id: 0,
            history_entry_count: 0,
            network_proxy: None,
            rollout_path: Some(PathBuf::from(
                "/home/ai/.codex/sessions/2026/04/21/rollout-test.jsonl",
            )),
        }
    }

    fn test_turn(id: &str, status: TurnStatus, items: Vec<ThreadItem>) -> Turn {
        Turn {
            id: id.to_string(),
            items,
            status,
            error: None,
            started_at: Some(1),
            completed_at: Some(2),
            duration_ms: Some(1500),
        }
    }

    #[test]
    fn completion_email_uses_full_agent_message_body() {
        let turn_id = "turn-1";
        let events = vec![
            ThreadBufferedEvent::Notification(ServerNotification::ItemCompleted(
                ItemCompletedNotification {
                    thread_id: test_thread_id().to_string(),
                    turn_id: turn_id.to_string(),
                    item: ThreadItem::UserMessage {
                        id: "user-1".to_string(),
                        content: vec![AppServerUserInput::Text {
                            text: "Finish the release sync and summarize what changed.".to_string(),
                            text_elements: Vec::new(),
                        }],
                    },
                },
            )),
            ThreadBufferedEvent::Notification(ServerNotification::ItemCompleted(
                ItemCompletedNotification {
                    thread_id: test_thread_id().to_string(),
                    turn_id: turn_id.to_string(),
                    item: ThreadItem::CommandExecution {
                        id: "cmd-1".to_string(),
                        command: "cargo test -p codex-tui".to_string(),
                        cwd: AbsolutePathBuf::try_from(PathBuf::from(
                            "/home/ai/Development/losangelex/codex-rs",
                        ))
                        .expect("cwd"),
                        process_id: None,
                        source: Default::default(),
                        status: CommandExecutionStatus::Completed,
                        command_actions: Vec::new(),
                        aggregated_output: None,
                        exit_code: Some(0),
                        duration_ms: Some(2400),
                    },
                },
            )),
            ThreadBufferedEvent::Notification(ServerNotification::ItemCompleted(
                ItemCompletedNotification {
                    thread_id: test_thread_id().to_string(),
                    turn_id: turn_id.to_string(),
                    item: ThreadItem::FileChange {
                        id: "patch-1".to_string(),
                        changes: vec![
                            FileUpdateChange {
                                path: "tui/src/app/email_bridge.rs".to_string(),
                                kind: PatchChangeKind::Update { move_path: None },
                                diff: String::new(),
                            },
                            FileUpdateChange {
                                path: "tui/src/app/email_bridge_format.rs".to_string(),
                                kind: PatchChangeKind::Add,
                                diff: String::new(),
                            },
                        ],
                        status: PatchApplyStatus::Completed,
                    },
                },
            )),
            ThreadBufferedEvent::Notification(ServerNotification::ItemCompleted(
                ItemCompletedNotification {
                    thread_id: test_thread_id().to_string(),
                    turn_id: turn_id.to_string(),
                    item: ThreadItem::AgentMessage {
                        id: "agent-1".to_string(),
                        text: "Release sync complete.\n\nI adapted the email bridge so completion notices send the final assistant message first.\nThe context and activity details are still included below for reply routing.".to_string(),
                        phase: None,
                        memory_citation: None,
                    },
                },
            )),
            ThreadBufferedEvent::Notification(ServerNotification::TurnCompleted(
                codex_app_server_protocol::TurnCompletedNotification {
                    thread_id: test_thread_id().to_string(),
                    turn: test_turn(turn_id, TurnStatus::Completed, Vec::new()),
                },
            )),
        ];
        let snapshot = EmailThreadSnapshot::from_state(
            test_thread_id(),
            "Release agent".to_string(),
            Some(test_session()),
            &[],
            &events,
            None,
        );

        let (subject, body) = format_completion_email(&snapshot, "[Losangelex]", "abc123");

        assert_eq!(
            subject,
            "[Losangelex] ozzz / Release agent completed work [lx:abc123]"
        );
        assert!(body.starts_with("Release sync complete.\n\nI adapted the email bridge"));
        assert!(body.contains("Recent user request:"));
        assert!(!body.contains("Latest agent response:"));
        assert!(
            body.contains(
                "- Command `cargo test -p codex-tui` in codex-rs (completed, exit 0, 2.4s)"
            )
        );
        assert!(body.contains(
            "- File changes (completed): updated tui/src/app/email_bridge.rs, added tui/src/app/email_bridge_format.rs"
        ));
        assert!(body.contains("Thread context:"));
        assert!(body.contains("- Working directory: /home/ai/Development/ozzz"));
        assert!(body.contains("- Model: gpt-5.4 (openai)"));
    }

    #[test]
    fn status_email_prefers_current_turn_activity() {
        let turn_id = "turn-active";
        let events = vec![ThreadBufferedEvent::Notification(
            ServerNotification::ItemStarted(codex_app_server_protocol::ItemStartedNotification {
                thread_id: test_thread_id().to_string(),
                turn_id: turn_id.to_string(),
                item: ThreadItem::WebSearch {
                    id: "search-1".to_string(),
                    query: "aws ses inbound s3 permissions".to_string(),
                    action: None,
                },
            }),
        )];
        let snapshot = EmailThreadSnapshot::from_state(
            test_thread_id(),
            "Release agent".to_string(),
            Some(test_session()),
            &[],
            &events,
            Some(turn_id.to_string()),
        );

        let (_subject, body) = format_status_email(&snapshot, "[Losangelex]", "abc123");

        assert!(body.contains("Status: active"));
        assert!(body.contains("Turn ID: turn-active"));
        assert!(body.contains("Current activity:"));
        assert!(body.contains("- Web search: aws ses inbound s3 permissions"));
    }

    #[test]
    fn request_user_input_email_includes_prompt() {
        let snapshot = EmailThreadSnapshot::from_state(
            test_thread_id(),
            "Release agent".to_string(),
            Some(test_session()),
            &[],
            &[],
            Some("turn-input".to_string()),
        );

        let (_subject, body) = format_request_user_input_email(
            &snapshot,
            "[Losangelex]",
            "abc123",
            "Deploy target: Which environment should I use?\n- staging: Safe validation\n- prod: Live traffic",
        );

        assert!(body.contains("Structured input needed:"));
        assert!(body.contains("Deploy target: Which environment should I use?"));
        assert!(body.contains("Email replies do not resolve structured prompts yet."));
    }
}
