//! Cold replay of the actual persisted checkpoint carrier; no model semantic claim.
use super::tests::make_session_and_context;
use super::*;
use codex_history::NativeContextCheckpointMode;
use codex_protocol::protocol::ThreadHistoryMode;
use codex_protocol::protocol::UserMessageEvent;
use pretty_assertions::assert_eq;
use serde_json::json;

#[tokio::test]
async fn native_checkpoint_cold_replay_restores_baseline_and_keeps_later_updates() {
    let (session, mut turn) = make_session_and_context().await;
    let reference = turn.to_turn_context_item();
    for mode in [
        NativeContextCheckpointMode::StepBoundary,
        NativeContextCheckpointMode::IdleRequest,
    ] {
        for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
            turn.history_mode = history_mode;
            let checkpoint: CompactedItem = serde_json::from_value(json!({
                "message": "", "replacement_history": [{
                    "type":"message","role":"developer",
                    "content":[{"type":"input_text","text":"exact native context"}]
                }],
                "window_number": 1,
                "resume_metadata": {
                    "multi_agent_version": null, "last_started_turn_id": "original-turn",
                    "previous_turn_settings": null,
                    "native_context": {
                        "schema":"lax-native-context-checkpoint/v1",
                        "thread_id":session.thread_id.to_string(), "context_id":"original-context",
                        "mode":mode,
                        "world_state":{"full":true,"state":{"environment":{"version":1,"keep":"retained"}}},
                        "reference_context":reference
                    }
                }
            })).unwrap();
            let mut records = vec![RolloutItem::Compacted(checkpoint)];
            // Cold reopen goes through the existing rollout wire, never saved live handles.
            let reopen = |items: &Vec<RolloutItem>| {
                serde_json::from_slice::<Vec<RolloutItem>>(&serde_json::to_vec(items).unwrap())
                    .unwrap()
            };
            let cold = session
                .reconstruct_history_from_rollout(&turn, &reopen(&records))
                .await;
            assert_eq!(cold.reference_context_item, Some(reference.clone()));
            assert_eq!(
                serde_json::to_value(cold.world_state_baseline).unwrap(),
                json!({"environment":{"version":1,"keep":"retained"}})
            );
            assert_eq!(cold.last_started_turn_id.as_deref(), Some("original-turn"));
            records.push(RolloutItem::WorldState(WorldStateItem::patch(
                serde_json::from_value(json!({"environment":{"version":2}})).unwrap(),
            )));
            let updated = session
                .reconstruct_history_from_rollout(&turn, &reopen(&records))
                .await;
            assert_eq!(updated.reference_context_item, Some(reference.clone()));
            assert_eq!(
                serde_json::to_value(updated.world_state_baseline).unwrap(),
                json!({"environment":{"version":2,"keep":"retained"}})
            );
            let mut later = reference.clone();
            later.model = "later-model".into();
            later.turn_id = Some("later-turn".into());
            records.extend([
                RolloutItem::EventMsg(EventMsg::UserMessage(UserMessageEvent {
                    message: "later legitimate input".into(),
                    ..Default::default()
                })),
                RolloutItem::TurnContext(later.clone()),
            ]);
            let later_cold = session
                .reconstruct_history_from_rollout(&turn, &reopen(&records))
                .await;
            assert_eq!(later_cold.reference_context_item, Some(later));
            assert_eq!(
                serde_json::to_value(later_cold.world_state_baseline).unwrap(),
                json!({"environment":{"version":2,"keep":"retained"}})
            );
        }
    }
}
