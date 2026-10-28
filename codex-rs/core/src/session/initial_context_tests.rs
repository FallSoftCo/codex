//! Actual native acquisition/render boundary, not model-semantic evidence.
use super::*;
use pretty_assertions::assert_eq;

fn wire(
    template: &InitialContextTemplate,
    turn: &str,
    ids: AutoCompactWindowIds,
) -> Vec<ResponseItem> {
    crate::context_manager::updates::merge_world_state_updates(
        template.render(turn, ids).unwrap().0,
    )
}

#[tokio::test]
async fn acquired_context_renders_without_session_and_uses_target_window_ids() {
    let (session, turn) = super::super::tests::make_session_and_context().await;
    let session = Arc::new(session);
    let step = session
        .capture_step_context(Arc::new(turn), &tokio_util::sync::CancellationToken::new())
        .await
        .unwrap();
    let world = session
        .build_world_state_for_step(&step, /*new_window*/ true)
        .await
        .unwrap();
    let mut material = session.collect_initial_context(&step).await;
    // Exercise typed window metadata even if the test profile disables hints.
    material.token_budget_path = Some(AgentPath::root());
    let template = material.capture(&world);
    let old = session.state.lock().await.auto_compact_window_ids();
    let next = AutoCompactWindowIds {
        first_window_id: old.first_window_id,
        previous_window_id: Some(old.window_id),
        window_id: uuid::Uuid::now_v7(),
    };
    let turn_id = step.turn.sub_id.clone();
    let before = session
        .clone_history()
        .await
        .raw_items()
        .cloned()
        .collect::<Vec<_>>();
    let first = wire(&template, &turn_id, old);
    assert_eq!(wire(&template, &turn_id, old), first);
    assert_eq!(
        session
            .clone_history()
            .await
            .raw_items()
            .cloned()
            .collect::<Vec<_>>(),
        before
    );
    drop(step);
    drop(session);
    drop(material);
    drop(world);
    let cold: InitialContextTemplate =
        serde_json::from_slice(&serde_json::to_vec(&template).unwrap()).unwrap();
    // No session, world, dynamic fragment, extension registry or MCP handle remains.
    assert_eq!(wire(&cold, &turn_id, old), first);
    let replacement = wire(&cold, &turn_id, next);
    let text = serde_json::to_string(&replacement).unwrap();
    assert!(text.contains(&format!("Current context window id: {}", next.window_id)));
    assert!(text.contains(&format!("Previous context window id: {}", old.window_id)));
    assert!(!text.contains(&format!("Current context window id: {}", old.window_id)));
    // Deliberately broken stale-ID rendering must not satisfy the target oracle.
    assert!(
        !serde_json::to_string(&first)
            .unwrap()
            .contains(&format!("Current context window id: {}", next.window_id))
    );
    assert_ne!(replacement, first);
}

#[tokio::test]
async fn cold_initial_context_render_never_reinvokes_world_extension_callbacks() {
    use codex_extension_api::RenderedWorldStateFragment;
    use codex_extension_api::WorldStateSectionContribution;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;

    let (session, turn) = super::super::tests::make_session_and_context().await;
    let session = Arc::new(session);
    let step = session
        .capture_step_context(Arc::new(turn), &tokio_util::sync::CancellationToken::new())
        .await
        .unwrap();
    let mut world = session
        .build_world_state_for_step(&step, /*new_window*/ true)
        .await
        .unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let callback_calls = Arc::clone(&calls);
    let handle = Arc::new(());
    let weak_handle = Arc::downgrade(&handle);
    world.add_extension_section(WorldStateSectionContribution::new(
        "initial_context_callback_probe",
        move |_| {
            let _held = &handle;
            callback_calls.fetch_add(1, Ordering::SeqCst);
            (
                Some(serde_json::json!({"revision": 1})),
                Some(RenderedWorldStateFragment::new(
                    "developer",
                    ("<probe>", "</probe>"),
                    codex_protocol::models::input_text("owned extension content"),
                )),
            )
        },
    ));
    let material = session.collect_initial_context(&step).await;
    let template = material.capture(&world);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    // This is the deliberately broken old path: WorldState is not inert data.
    let _broken_preview = world.render_full();
    assert_ne!(calls.load(Ordering::SeqCst), 1);
    let after_broken_control = calls.load(Ordering::SeqCst);
    let ids = session.state.lock().await.auto_compact_window_ids();
    let turn_id = step.turn.sub_id.clone();
    let expected = wire(&template, &turn_id, ids);
    let bytes = serde_json::to_vec(&template).unwrap();
    drop(template);
    drop(material);
    drop(world);
    drop(step);
    drop(session);
    assert!(weak_handle.upgrade().is_none());
    let cold: InitialContextTemplate = serde_json::from_slice(&bytes).unwrap();
    for _ in 0..3 {
        assert_eq!(wire(&cold, &turn_id, ids), expected);
        assert_eq!(calls.load(Ordering::SeqCst), after_broken_control);
    }
    let mut forged = cold.clone();
    forged.window = Some(CapturedWindowContext {
        index: forged.items.len() + 1,
        agent_path: AgentPath::root(),
        hints: codex_context_fragments::message_from_parts("developer", vec![]),
    });
    assert!(forged.render(&turn_id, ids).is_err());
    forged.window.as_mut().unwrap().index = 0;
    forged.window.as_mut().unwrap().hints =
        codex_context_fragments::message_from_parts("user", vec![]);
    assert!(forged.render(&turn_id, ids).is_err());
}
