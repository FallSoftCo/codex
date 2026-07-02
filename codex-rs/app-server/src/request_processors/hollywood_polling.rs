use crate::hollywood::HollywoodClassifiedMessage;
use crate::hollywood::HollywoodPendingSemanticWake;
use crate::hollywood::collaboration_first_policy_enabled;
use crate::hollywood::poll_messages;
use crate::thread_state::ThreadState;
use crate::thread_status::ThreadWatchManager;
use codex_app_server_protocol::HollywoodMessageAttention;
use codex_app_server_protocol::HollywoodMessageKind;
use codex_app_server_protocol::HollywoodResponsePolicy;
use codex_app_server_protocol::ThreadStatus;
use codex_core::CodexThread;
use codex_protocol::ThreadId;
use codex_protocol::protocol::HollywoodInputMessage;
use codex_protocol::protocol::HollywoodSyntheticBrief;
use reqwest::Client;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::Mutex;

pub(super) fn hollywood_polling_enabled() -> bool {
    collaboration_first_policy_enabled()
}

pub(super) async fn poll_hollywood_for_thread(
    client: &Client,
    conversation_id: ThreadId,
    conversation: &Arc<CodexThread>,
    thread_state: &Arc<Mutex<ThreadState>>,
    thread_watch_manager: &ThreadWatchManager,
) {
    let status = thread_watch_manager
        .loaded_status_for_thread(&conversation_id.to_string())
        .await;
    if !matches!(status, ThreadStatus::Idle) {
        return;
    }

    let poll_targets = {
        let thread_state = thread_state.lock().await;
        let Some(config) = thread_state.hollywood.config() else {
            return;
        };
        let rooms = config
            .all_rooms()
            .into_iter()
            .map(|room| {
                let after_id = thread_state.hollywood.last_seen_message_id(&room);
                (room, after_id)
            })
            .collect::<Vec<_>>();
        let thread_name = thread_state
            .hollywood
            .registry_thread_name()
            .map(ToOwned::to_owned);
        (config, rooms, thread_name)
    };
    let (config, rooms, thread_name) = poll_targets;

    for (room, after_id) in rooms {
        let poll_result = match poll_messages(
            client,
            &config,
            &room,
            after_id,
            conversation_id,
            thread_name.as_deref(),
        )
        .await
        {
            Ok(result) => result,
            Err(err) => {
                tracing::warn!(
                    "failed to poll Hollywood room {room} for thread {conversation_id}: {err}"
                );
                continue;
            }
        };
        let followup = select_hollywood_followup(&poll_result.messages, &config.room)
            .map(classified_message_to_hollywood_input);

        let should_start = {
            let mut thread_state = thread_state.lock().await;
            thread_state.hollywood.note_room_snapshot(
                &room,
                poll_result.room_state.as_ref(),
                poll_result.last_id,
            );

            let has_followup = if let Some(message) = followup.as_ref() {
                thread_state
                    .hollywood
                    .set_last_seen_message_id(&room, after_id);
                thread_state
                    .hollywood
                    .queue_semantic_wake(HollywoodPendingSemanticWake {
                        dedupe_key: format!("{}:{}", message.room, message.message_id),
                        room: message.room.clone(),
                        brief: message
                            .synthetic_brief
                            .clone()
                            .unwrap_or(HollywoodSyntheticBrief {
                                wake_reason: Some("hollywood_message".to_string()),
                                semantic_kind: Some("message".to_string()),
                                coordination_policy: None,
                                coordination_phase: None,
                                coordination_role: None,
                                coordination_epoch: None,
                                summary: Some(message.body.clone()),
                                facts: Vec::new(),
                                suggested_actions: Vec::new(),
                                stay_silent_if_no_actionable_delta: !message.requires_response,
                            }),
                    });
                true
            } else {
                thread_state
                    .hollywood
                    .set_last_seen_message_id(&room, poll_result.last_id);
                false
            };
            has_followup
                && thread_state
                    .hollywood
                    .should_start_autonomous_turn(Instant::now())
        };

        if let Some(message) = followup
            && should_start
        {
            let message_id = message.message_id;
            {
                let mut thread_state = thread_state.lock().await;
                let _ = thread_state.hollywood.take_pending_semantic_wakes();
                thread_state.hollywood.mark_autonomous_turn_pending();
            }
            if let Err(err) = conversation.submit_hollywood_followup(message).await {
                tracing::warn!(
                    "failed to submit Hollywood follow-up for thread {conversation_id}: {err}"
                );
                thread_state
                    .lock()
                    .await
                    .hollywood
                    .clear_autonomous_turn_pending();
            } else {
                thread_state
                    .lock()
                    .await
                    .hollywood
                    .set_last_seen_message_id(&room, message_id);
            }
            break;
        }
    }
}

fn select_hollywood_followup<'a>(
    messages: &'a [HollywoodClassifiedMessage],
    primary_room: &str,
) -> Option<&'a HollywoodClassifiedMessage> {
    messages
        .iter()
        .filter(|message| should_start_hollywood_followup(message, primary_room))
        .min_by_key(|message| hollywood_followup_priority(message))
}

fn hollywood_followup_priority(message: &HollywoodClassifiedMessage) -> (u8, i64) {
    let notification = &message.notification_message;
    let priority = if message_requires_response(message) {
        0
    } else {
        match message.attention {
            HollywoodMessageAttention::Focused => 1,
            HollywoodMessageAttention::Broadcast => 2,
            HollywoodMessageAttention::Broad => 3,
            HollywoodMessageAttention::Ambient => 4,
        }
    };
    (priority, notification.id)
}

fn should_start_hollywood_followup(
    message: &HollywoodClassifiedMessage,
    primary_room: &str,
) -> bool {
    if message.self_authored {
        return false;
    }
    let in_primary_room = message.notification_message.room == primary_room;
    if !in_primary_room && !message_targets_this_session(message) {
        return false;
    }
    if message_requires_response(message) {
        return true;
    }
    false
}

fn message_requires_response(message: &HollywoodClassifiedMessage) -> bool {
    let notification = &message.notification_message;
    matches!(
        notification.response_policy,
        HollywoodResponsePolicy::Required
    ) || message_targets_this_session(message)
}

fn message_targets_this_session(message: &HollywoodClassifiedMessage) -> bool {
    let notification = &message.notification_message;
    message.mentioned
        || matches!(notification.message_kind, HollywoodMessageKind::Direct)
        || notification.recipient_id.is_some()
}

fn classified_message_to_hollywood_input(
    message: &HollywoodClassifiedMessage,
) -> HollywoodInputMessage {
    let notification = &message.notification_message;
    let requires_response = message_requires_response(message);
    let body = notification.body.clone();
    HollywoodInputMessage {
        message_id: notification.id,
        room: notification.room.clone(),
        sender_id: notification
            .sender_id
            .clone()
            .unwrap_or_else(|| "hollywood-unknown".to_string()),
        body: body.clone(),
        mentions: notification.mentions.clone(),
        attention: Some(hollywood_attention_name(message.attention).to_string()),
        message_kind: Some(hollywood_message_kind_name(notification.message_kind).to_string()),
        obligation: Some(
            if requires_response {
                "obligation"
            } else {
                "attention"
            }
            .to_string(),
        ),
        synthetic_brief: Some(HollywoodSyntheticBrief {
            wake_reason: Some("hollywood_message".to_string()),
            semantic_kind: Some(hollywood_message_kind_name(notification.message_kind).to_string()),
            coordination_policy: None,
            coordination_phase: None,
            coordination_role: None,
            coordination_epoch: None,
            summary: Some(body),
            facts: Vec::new(),
            suggested_actions: Vec::new(),
            stay_silent_if_no_actionable_delta: !requires_response,
        }),
        requires_response,
    }
}

fn hollywood_attention_name(attention: HollywoodMessageAttention) -> &'static str {
    match attention {
        HollywoodMessageAttention::Focused => "focused",
        HollywoodMessageAttention::Broadcast => "broadcast",
        HollywoodMessageAttention::Ambient => "ambient",
        HollywoodMessageAttention::Broad => "broad",
    }
}

fn hollywood_message_kind_name(kind: HollywoodMessageKind) -> &'static str {
    match kind {
        HollywoodMessageKind::Ambient => "ambient",
        HollywoodMessageKind::Broadcast => "broadcast",
        HollywoodMessageKind::Direct => "direct",
    }
}

#[cfg(test)]
#[path = "hollywood_polling_tests.rs"]
mod tests;
