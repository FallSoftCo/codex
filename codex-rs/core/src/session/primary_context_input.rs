//! First-sample admission gate; no reset, polling model or synthetic human input.
use crate::primary_context_input::PrimaryContextInput;
use crate::primary_context_input::validate;
use crate::session::TurnInput;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use codex_protocol::context_input::ContextInputParams;
use codex_protocol::context_refill::ContextRefillPurpose;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::inference_completion::InferenceCompletionPolicy;
use codex_protocol::models::FunctionCallOutputBody;
use codex_protocol::models::ResponseItem;
use serde::Deserialize;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Notice {
    purpose: ContextRefillPurpose,
    material_ids: Vec<String>,
}

pub(super) async fn admit(
    session: &Session,
    turn: &TurnContext,
    input: &[TurnInput],
    cancel: &CancellationToken,
) -> CodexResult<()> {
    let Some(policy) = session
        .services
        .thread_extension_data
        .get::<PrimaryContextInput>()
    else {
        return Ok(());
    };
    // Reasons contain only protocol stages or validation diagnostics, never material.
    let held = |reason: &str| {
        CodexErr::Fatal(format!(
            "Original primary context input unavailable ({reason}); inspect original admission without replay"
        ))
    };
    if session
        .services
        .thread_extension_data
        .get::<InferenceCompletionPolicy>()
        .is_none_or(|p| *p != InferenceCompletionPolicy::HostTool)
    {
        return Err(held("host-tool policy"));
    }
    let [TurnInput::FunctionCallOutput(envelope)] = input else {
        return Err(held("normalized input kind"));
    };
    let ResponseItem::FunctionCallOutput {
        call_id: None,
        name: Some(name),
        output,
        ..
    } = &envelope.item
    else {
        return Err(held("named admission output"));
    };
    if name != "context_material_available" {
        return Err(held("admission output name"));
    }
    let FunctionCallOutputBody::Text(text) = &output.body else {
        return Err(held("admission text encoding"));
    };
    let notice: Notice = serde_json::from_str(text).map_err(|_| held("admission notice schema"))?;
    if notice.purpose != policy.purpose
        || notice.material_ids.is_empty()
        || notice.material_ids.len() > 16
        || policy.purpose == ContextRefillPurpose::Writer && notice.material_ids.len() != 1
        || notice
            .material_ids
            .iter()
            .any(|id| Uuid::parse_str(id).is_err())
        || notice
            .material_ids
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != notice.material_ids.len()
    {
        return Err(held("admission purpose/material scope"));
    }
    let request = ContextInputParams {
        thread_id: session.thread_id.to_string(),
        turn_id: turn.sub_id.clone(),
        operation_id: Uuid::now_v7().to_string(),
        context_id: policy.context_id.clone(),
        purpose: policy.purpose.clone(),
        material_ids: notice.material_ids,
    };
    let epoch = policy.host.owner_epoch();
    if cancel.is_cancelled() {
        return Err(CodexErr::TurnAborted);
    }
    if !policy.host.is_current(epoch) {
        return Err(held("owner before callback"));
    }
    let disconnected = policy.host.owner_disconnected();
    let response = tokio::select! {
        biased;
        _ = cancel.cancelled() => return Err(CodexErr::TurnAborted),
        _ = disconnected.cancelled() => return Err(held("owner disconnected")),
        value = tokio::time::timeout(std::time::Duration::from_secs(30),
            policy.host.primary_input(epoch, request.clone())) =>
            value.map_err(|_| held("callback timeout"))?
                .map_err(|error| held(&format!("callback transport: {error}")))?,
    };
    if cancel.is_cancelled() {
        return Err(CodexErr::TurnAborted);
    }
    if !policy.host.is_current(epoch) {
        return Err(held("owner after callback"));
    }
    let items = validate(&request, &response).map_err(|reason| held(&reason))?;
    // Observe the original strict append/flush result, even during cancellation.
    if !items.is_empty() {
        session
            .try_record_tool_context(turn, items)
            .await
            .map_err(|error| held(&format!("history persistence: {error}")))?;
    }
    if cancel.is_cancelled() {
        return Err(CodexErr::TurnAborted);
    }
    if !policy.host.is_current(epoch) {
        return Err(held("owner after persistence"));
    }
    Ok(())
}
