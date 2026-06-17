use super::*;
use codex_app_server_protocol::HollywoodMessage;
use pretty_assertions::assert_eq;

fn classified_message(
    id: i64,
    message_kind: HollywoodMessageKind,
    response_policy: HollywoodResponsePolicy,
    attention: HollywoodMessageAttention,
) -> HollywoodClassifiedMessage {
    HollywoodClassifiedMessage {
        notification_message: HollywoodMessage {
            id,
            room: "repo/losangelex".to_string(),
            sender_id: Some(format!("agent-{id}")),
            recipient_id: None,
            message_kind,
            response_policy,
            body: format!("message {id}"),
            created_at: "2026-06-16T00:00:00Z".to_string(),
            mentions: Vec::new(),
        },
        attention,
        mentioned: false,
        self_authored: false,
    }
}

#[test]
fn select_hollywood_followup_prioritizes_required_direct_message() {
    let messages = vec![
        classified_message(
            3,
            HollywoodMessageKind::Broadcast,
            HollywoodResponsePolicy::Optional,
            HollywoodMessageAttention::Broadcast,
        ),
        classified_message(
            4,
            HollywoodMessageKind::Direct,
            HollywoodResponsePolicy::Required,
            HollywoodMessageAttention::Focused,
        ),
    ];

    let selected = select_hollywood_followup(&messages).expect("selected followup");

    assert_eq!(selected.notification_message.id, 4);
}

#[test]
fn select_hollywood_followup_ignores_no_response_broadcast() {
    let messages = vec![classified_message(
        1,
        HollywoodMessageKind::Broadcast,
        HollywoodResponsePolicy::None,
        HollywoodMessageAttention::Broadcast,
    )];

    assert!(select_hollywood_followup(&messages).is_none());
}
