use super::*;
use codex_app_server_protocol::HollywoodMessage;
use pretty_assertions::assert_eq;
use serial_test::serial;

struct EnvGuard {
    key: &'static str,
    previous: Option<String>,
}

impl EnvGuard {
    fn set(key: &'static str, value: Option<&str>) -> Self {
        let previous = std::env::var(key).ok();
        match value {
            Some(value) => unsafe { std::env::set_var(key, value) },
            None => unsafe { std::env::remove_var(key) },
        }
        Self { key, previous }
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        match self.previous.as_deref() {
            Some(value) => unsafe { std::env::set_var(self.key, value) },
            None => unsafe { std::env::remove_var(self.key) },
        }
    }
}

#[test]
#[serial]
fn hollywood_polling_enabled_by_default() {
    let _policy = EnvGuard::set("LOSANGELEX_COLLABORATION_FIRST", None);
    let _debug = EnvGuard::set("LOSANGELEX_COLLABORATION_FIRST_DEBUG", None);

    assert!(hollywood_polling_enabled());
}

#[test]
#[serial]
fn hollywood_polling_can_be_disabled() {
    let _policy = EnvGuard::set("LOSANGELEX_COLLABORATION_FIRST", Some("0"));
    let _debug = EnvGuard::set("LOSANGELEX_COLLABORATION_FIRST_DEBUG", None);

    assert!(!hollywood_polling_enabled());
}

#[test]
#[serial]
fn hollywood_polling_debug_env_still_enables() {
    let _policy = EnvGuard::set("LOSANGELEX_COLLABORATION_FIRST", Some("0"));
    let _debug = EnvGuard::set("LOSANGELEX_COLLABORATION_FIRST_DEBUG", Some("1"));

    assert!(hollywood_polling_enabled());
}

fn classified_message(
    id: i64,
    message_kind: HollywoodMessageKind,
    response_policy: HollywoodResponsePolicy,
    attention: HollywoodMessageAttention,
) -> HollywoodClassifiedMessage {
    classified_message_in_room(
        id,
        "repo/losangelex",
        message_kind,
        response_policy,
        attention,
    )
}

fn classified_message_in_room(
    id: i64,
    room: &str,
    message_kind: HollywoodMessageKind,
    response_policy: HollywoodResponsePolicy,
    attention: HollywoodMessageAttention,
) -> HollywoodClassifiedMessage {
    HollywoodClassifiedMessage {
        notification_message: HollywoodMessage {
            id,
            room: room.to_string(),
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

    let selected =
        select_hollywood_followup(&messages, "repo/losangelex").expect("selected followup");

    assert_eq!(selected.notification_message.id, 4);
}

#[test]
fn select_hollywood_followup_ignores_optional_broadcast() {
    let messages = vec![classified_message(
        1,
        HollywoodMessageKind::Broadcast,
        HollywoodResponsePolicy::Optional,
        HollywoodMessageAttention::Broadcast,
    )];

    assert!(select_hollywood_followup(&messages, "repo/losangelex").is_none());
}

#[test]
fn select_hollywood_followup_accepts_required_primary_room_broadcast() {
    let messages = vec![classified_message(
        1,
        HollywoodMessageKind::Broadcast,
        HollywoodResponsePolicy::Required,
        HollywoodMessageAttention::Broadcast,
    )];

    let selected =
        select_hollywood_followup(&messages, "repo/losangelex").expect("selected followup");

    assert_eq!(selected.notification_message.id, 1);
}

#[test]
fn select_hollywood_followup_ignores_required_observed_room_broadcast() {
    let messages = vec![classified_message_in_room(
        1,
        "main",
        HollywoodMessageKind::Broadcast,
        HollywoodResponsePolicy::Required,
        HollywoodMessageAttention::Broadcast,
    )];

    assert!(select_hollywood_followup(&messages, "repo/losangelex").is_none());
}

#[test]
fn select_hollywood_followup_accepts_targeted_observed_room_message() {
    let messages = vec![classified_message_in_room(
        1,
        "main",
        HollywoodMessageKind::Direct,
        HollywoodResponsePolicy::Optional,
        HollywoodMessageAttention::Focused,
    )];

    let selected =
        select_hollywood_followup(&messages, "repo/losangelex").expect("selected followup");

    assert_eq!(selected.notification_message.id, 1);
}

#[test]
fn select_hollywood_followup_ignores_self_authored_targeted_message() {
    let mut message = classified_message(
        1,
        HollywoodMessageKind::Direct,
        HollywoodResponsePolicy::Required,
        HollywoodMessageAttention::Focused,
    );
    message.self_authored = true;
    let messages = vec![message];

    assert!(select_hollywood_followup(&messages, "repo/losangelex").is_none());
}

#[test]
fn targeted_observed_room_message_becomes_required_hollywood_input() {
    let messages = vec![classified_message_in_room(
        1,
        "main",
        HollywoodMessageKind::Direct,
        HollywoodResponsePolicy::Optional,
        HollywoodMessageAttention::Focused,
    )];
    let selected =
        select_hollywood_followup(&messages, "repo/losangelex").expect("selected followup");

    let input = classified_message_to_hollywood_input(selected);

    assert_eq!(input.message_id, 1);
    assert_eq!(input.room, "main");
    assert_eq!(input.attention, Some("focused".to_string()));
    assert_eq!(input.message_kind, Some("direct".to_string()));
    assert_eq!(input.obligation, Some("obligation".to_string()));
    assert_eq!(input.requires_response, true);
    assert_eq!(
        input
            .synthetic_brief
            .expect("synthetic brief should be present")
            .stay_silent_if_no_actionable_delta,
        false
    );
}

#[test]
fn primary_room_required_broadcast_becomes_required_hollywood_input() {
    let messages = vec![classified_message(
        1,
        HollywoodMessageKind::Broadcast,
        HollywoodResponsePolicy::Required,
        HollywoodMessageAttention::Broadcast,
    )];
    let selected =
        select_hollywood_followup(&messages, "repo/losangelex").expect("selected followup");

    let input = classified_message_to_hollywood_input(selected);

    assert_eq!(input.message_id, 1);
    assert_eq!(input.room, "repo/losangelex");
    assert_eq!(input.attention, Some("broadcast".to_string()));
    assert_eq!(input.message_kind, Some("broadcast".to_string()));
    assert_eq!(input.obligation, Some("obligation".to_string()));
    assert_eq!(input.requires_response, true);
}
