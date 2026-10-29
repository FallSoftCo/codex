//! Native acquisition and rollout replay integration; not model behavior proof.
use super::*;
use codex_history::ResponseItemEnvelope;
use codex_protocol::context_refill::*;
use codex_protocol::protocol::ThreadHistoryMode;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::future::Future;
use std::pin::Pin;
use tokio_util::sync::CancellationToken;

struct NoCalls;
impl crate::context_refill::ContextRefillHost for NoCalls {
    fn owner_epoch(&self) -> u64 {
        1
    }
    fn is_current(&self, epoch: u64) -> bool {
        epoch == 1
    }
    fn owner_disconnected(&self) -> CancellationToken {
        CancellationToken::new()
    }
    fn refill(
        &self,
        _: u64,
        _: ContextWindowRefillParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowRefillResponse>> + Send + '_>> {
        panic!("producer acquisition/read must not request a refill")
    }
    fn installed(
        &self,
        _: u64,
        _: ContextWindowInstalledParams,
    ) -> Pin<Box<dyn Future<Output = io::Result<ContextWindowInstalledResponse>> + Send + '_>> {
        panic!("producer acquisition/read must not install")
    }
}

fn enable(session: &Session) {
    session
        .services
        .thread_extension_data
        .insert(AutomaticContextRefill {
            context_id: "producer-context".into(),
            purpose: ContextRefillPurpose::Writer,
            evidence: RetainedContextEvidence::WholeItemsV1,
            host: Arc::new(NoCalls),
        });
}

fn rendered(template: &InitialContextTemplate, ids: AutoCompactWindowIds) -> Vec<ResponseItem> {
    crate::context_manager::updates::merge_world_state_updates(
        template.render("original-turn", ids).unwrap().0,
    )
}

#[tokio::test]
async fn initial_context_producer_reuses_actual_turn_acquisition_for_emission() {
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    struct Changing(Arc<AtomicUsize>);
    impl codex_extension_api::ContextContributor for Changing {
        fn contribute_turn_context<'a>(
            &'a self,
            _: TurnContextContributionInput<'a>,
        ) -> Pin<Box<dyn Future<Output = Vec<codex_extension_api::PromptFragment>> + Send + 'a>>
        {
            Box::pin(async move {
                let call = self.0.fetch_add(1, Ordering::SeqCst) + 1;
                vec![codex_extension_api::PromptFragment::developer_policy(
                    format!("acquired turn fact {call}"),
                    codex_extension_api::ContentItemKind("test.same_cut".into()),
                )]
            })
        }
    }
    let (mut session, turn) = super::super::tests::make_session_and_context().await;
    let calls = Arc::new(AtomicUsize::new(0));
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::new();
    builder.prompt_contributor(Arc::new(Changing(Arc::clone(&calls))));
    session.services.extensions = Arc::new(builder.build());
    let session = Arc::new(session);
    enable(&session);
    let turn = Arc::new(turn);
    let first = session
        .capture_step_context(Arc::clone(&turn), &CancellationToken::new())
        .await
        .unwrap();
    session
        .record_context_updates_and_set_reference_context_item(&first)
        .await
        .unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    drop(first);
    let mut turn = Arc::try_unwrap(turn).unwrap();
    turn.sub_id = "next-legitimate-turn".into();
    let next = session
        .capture_step_context(Arc::new(turn), &CancellationToken::new())
        .await
        .unwrap();
    let old_len = session.clone_history().await.annotated_items().len();
    session
        .record_context_updates_and_set_reference_context_item(&next)
        .await
        .unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    let history = session.clone_history().await;
    let emitted = serde_json::to_string(
        &history.annotated_items()[old_len..]
            .iter()
            .map(|item| &item.item)
            .collect::<Vec<_>>(),
    )
    .unwrap();
    assert!(emitted.contains("acquired turn fact 2"));
    let ids = session.state.lock().await.auto_compact_window_ids();
    let producer = read(
        &history,
        &session.thread_id.to_string(),
        "producer-context",
        ids,
    )
    .unwrap();
    let replay = serde_json::to_string(&rendered(&producer, ids)).unwrap();
    assert!(replay.contains("acquired turn fact 2"));
    assert!(!replay.contains("acquired turn fact 1"));
    assert!(!replay.contains("acquired turn fact 3"));
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}

#[tokio::test]
async fn initial_context_producer_acquires_at_normal_and_midturn_boundaries() {
    let (session, turn) = super::super::tests::make_session_and_context().await;
    let session = Arc::new(session);
    enable(&session);
    let step = session
        .capture_step_context(Arc::new(turn), &CancellationToken::new())
        .await
        .unwrap();
    session
        .record_context_updates_and_set_reference_context_item(&step)
        .await
        .unwrap();
    let ids = session.state.lock().await.auto_compact_window_ids();
    let thread = session.thread_id.to_string();
    let normal = session.clone_history().await;
    let expected = rendered(
        &read(&normal, &thread, "producer-context", ids).unwrap(),
        ids,
    );
    assert!(!expected.is_empty());
    session
        .record_step_world_state_if_changed(&step)
        .await
        .unwrap();
    let midturn = session.clone_history().await;
    assert_eq!(
        rendered(
            &read(&midturn, &thread, "producer-context", ids).unwrap(),
            ids
        ),
        expected
    );
    assert!(
        midturn
            .world_state_checkpoint()
            .unwrap()
            .native_context_producer
            .is_some()
    );
    // Original normal history remains usable; capture does not mutate its Arc snapshot.
    assert_eq!(
        rendered(
            &read(&normal, &thread, "producer-context", ids).unwrap(),
            ids
        ),
        expected
    );
    let before = serde_json::to_value(midturn.world_state_checkpoint()).unwrap();
    for _ in 0..3 {
        assert_eq!(
            rendered(
                &read(&midturn, &thread, "producer-context", ids).unwrap(),
                ids
            ),
            expected
        );
    }
    assert_eq!(
        serde_json::to_value(midturn.world_state_checkpoint()).unwrap(),
        before
    );
    let proposed = target_ids(
        ids,
        "producer-context",
        "review-operation",
        midturn.history_version(),
    );
    assert_ne!(proposed.window_id, ids.window_id);
    assert_eq!(proposed.previous_window_id, Some(ids.window_id));
    assert_eq!(
        target_ids(
            ids,
            "producer-context",
            "review-operation",
            midturn.history_version()
        )
        .window_id,
        proposed.window_id
    );
    let first = prefix(
        &midturn,
        &thread,
        "producer-context",
        &step.turn.sub_id,
        proposed,
    )
    .unwrap();
    assert_eq!(
        prefix(
            &midturn,
            &thread,
            "producer-context",
            &step.turn.sub_id,
            proposed
        )
        .unwrap(),
        first
    );
    let mut installed = midturn;
    installed.replace_annotated(first.clone());
    assert_eq!(
        super::super::context_prefix::read(&installed, &thread, "producer-context").unwrap(),
        first
    );
}

#[tokio::test]
async fn initial_context_producer_refuses_stale_forged_oversize_and_replaced_history() {
    let (session, turn) = super::super::tests::make_session_and_context().await;
    let session = Arc::new(session);
    enable(&session);
    let step = session
        .capture_step_context(Arc::new(turn), &CancellationToken::new())
        .await
        .unwrap();
    session
        .record_context_updates_and_set_reference_context_item(&step)
        .await
        .unwrap();
    let ids = session.state.lock().await.auto_compact_window_ids();
    let thread = session.thread_id.to_string();
    let history = session.clone_history().await;
    let original = history.native_context_producer().unwrap().clone();
    let check = |history: &ContextManager| source_digest(history, &thread, "producer-context", ids);
    assert!(read(&history, "forked-thread", "producer-context", ids).is_err());
    assert!(read(&history, &thread, "other-context", ids).is_err());
    let mut stale = history.clone();
    let mut reference = stale.reference_context_item().unwrap();
    reference.model = "changed-model".into();
    stale.set_reference_context_item(Some(reference));
    stale.set_native_context_producer(Some(original.clone()));
    assert!(check(&stale).is_err());
    stale = history.clone();
    stale.set_world_state_baseline(WorldStateSnapshot::default());
    stale.set_native_context_producer(Some(original.clone()));
    assert!(check(&stale).is_err());
    let mut forged = original.clone();
    forged["sha256"] = json!("0".repeat(64));
    stale = history.clone();
    stale.set_native_context_producer(Some(forged));
    assert!(check(&stale).is_err());
    stale.set_native_context_producer(Some(json!("x".repeat(MAX_PRODUCER_BYTES + 1))));
    assert!(check(&stale).is_err());
    stale = history.clone();
    stale.replace_annotated(history.annotated_items().to_vec());
    assert!(stale.native_context_producer().is_none());
    assert!(check(&stale).is_err());
    assert_eq!(history.native_context_producer(), Some(&original));
    assert_eq!(
        check(&history).unwrap(),
        original["sha256"].as_str().unwrap()
    );
}

#[tokio::test]
async fn initial_context_producer_cold_replay_obeys_surviving_world_segments() {
    for mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let (session, mut turn) = super::super::tests::make_session_and_context().await;
        turn.history_mode = mode;
        let session = Arc::new(session);
        enable(&session);
        let turn = Arc::new(turn);
        let step = session
            .capture_step_context(Arc::clone(&turn), &CancellationToken::new())
            .await
            .unwrap();
        session
            .record_context_updates_and_set_reference_context_item(&step)
            .await
            .unwrap();
        let ids = session.state.lock().await.auto_compact_window_ids();
        let history = session.clone_history().await;
        let checkpoint = history.world_state_checkpoint().unwrap();
        let reference = history.reference_context_item().unwrap();
        let thread = session.thread_id.to_string();
        let expected = rendered(
            &read(&history, &thread, "producer-context", ids).unwrap(),
            ids,
        );
        let records = vec![
            RolloutItem::WorldState(checkpoint.clone()),
            RolloutItem::TurnContext(reference.clone()),
        ];
        let reopen = |items: &Vec<RolloutItem>| {
            serde_json::from_slice::<Vec<RolloutItem>>(&serde_json::to_vec(items).unwrap()).unwrap()
        };
        let cold = session
            .reconstruct_history_from_rollout(&turn, &reopen(&records))
            .await;
        let mut restored = ContextManager::new();
        restored.set_reference_context_item(cold.reference_context_item);
        restored.set_world_state_baseline(cold.world_state_baseline.unwrap());
        restored.set_native_context_producer(cold.native_context_producer);
        assert_eq!(
            rendered(
                &read(&restored, &thread, "producer-context", ids).unwrap(),
                ids
            ),
            expected
        );
        // An ordinary later world record must invalidate the old complete producer,
        // even if it has an empty patch and leaves comparison hashes unchanged.
        let mut later = records.clone();
        later.push(RolloutItem::WorldState(WorldStateItem::patch(
            Default::default(),
        )));
        assert!(
            session
                .reconstruct_history_from_rollout(&turn, &reopen(&later))
                .await
                .native_context_producer
                .is_none()
        );
        // A reset without a producer cannot resurrect material from an old segment.
        later = records.clone();
        let reset: CompactedItem =
            serde_json::from_value(json!({"message":"reset", "replacement_history":[]})).unwrap();
        later.push(RolloutItem::Compacted(Box::new(reset)));
        assert!(
            session
                .reconstruct_history_from_rollout(&turn, &reopen(&later))
                .await
                .native_context_producer
                .is_none()
        );
    }
}

#[tokio::test]
async fn initial_context_producer_contains_complete_tools_not_last_incremental_batch() {
    use crate::context::world_state::TopLevelToolsState;
    use codex_prompts::ResolvedModelMessages;
    let (session, turn) = super::super::tests::make_session_and_context().await;
    let step = StepContext::for_test(Arc::new(turn));
    let messages = ResolvedModelMessages::from_model(&step.settings.model_info);
    let make_world = |names: &[&str]| {
        let mut world = WorldState::default();
        world.add_section(TopLevelToolsState::new(messages.incremental_tools(), names.iter().map(|name| json!({"type":"function","name":name,"description":format!("definition of {name}")})).collect(), /*metrics*/ None).unwrap());
        world
    };
    let material = session.collect_initial_context(&step).await;
    let old = material.capture(&make_world(&["unchanged", "obsolete"]));
    let current_world = make_world(&["unchanged", "new_tool"]);
    let current = material.capture(&current_world);
    let ids = session.state.lock().await.auto_compact_window_ids();
    let mut history = ContextManager::new();
    let reference = step.to_turn_context_item();
    history.set_reference_context_item(Some(reference.clone()));
    history.set_world_state_baseline(current.snapshot.clone());
    history.set_native_context_producer(Some(
        seal(
            session.thread_id.to_string(),
            "tools-context".into(),
            reference.clone(),
            reference,
            current,
            ids,
        )
        .unwrap(),
    ));
    let tools = |items: Vec<ResponseItem>| {
        items
            .into_iter()
            .filter_map(|item| match item {
                ResponseItem::AdditionalTools { tools, .. } => Some(tools.to_vec()),
                _ => None,
            })
            .flatten()
            .collect::<Vec<_>>()
    };
    let complete = tools(rendered(
        &read(
            &history,
            &session.thread_id.to_string(),
            "tools-context",
            ids,
        )
        .unwrap(),
        ids,
    ));
    assert_eq!(
        complete
            .iter()
            .map(|tool| tool["name"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["unchanged", "new_tool"]
    );
    let last_batch = crate::context_manager::updates::merge_world_state_updates(
        current_world
            .render_history_diff(Some(&old.snapshot), std::iter::empty())
            .1,
    );
    assert_ne!(tools(last_batch), complete); // broken last-batch-only control
    // An ordinary instruction-looking message does not seed the producer.
    let mut ordinary_history = history.clone();
    ordinary_history.replace_annotated(vec![ResponseItemEnvelope::new(serde_json::from_value(json!({"type":"message", "role":"user", "content":[{"type":"input_text","text":"not selected"}]})).unwrap())]);
    assert!(
        read(
            &ordinary_history,
            &session.thread_id.to_string(),
            "tools-context",
            ids
        )
        .is_err()
    );
}
