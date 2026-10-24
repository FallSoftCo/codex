//! Fork-owned context instructions follow the current executable tool contract.
use super::session::Session;
use super::step_context::StepContext;
use codex_protocol::inference_completion::InferenceCompletionPolicy;
use codex_tools::ToolName;

#[derive(Clone, Debug, Default)]
pub(super) struct LaxContextContract {
    pub(super) guidance: Option<String>,
    pub(super) reminder: Option<&'static str>,
    pub(super) fallback: Option<&'static str>,
}

impl LaxContextContract {
    pub(super) fn for_step(session: &Session, step: &StepContext) -> Self {
        let owner = session
            .services
            .thread_extension_data
            .get::<InferenceCompletionPolicy>()
            .map_or(InferenceCompletionPolicy::Model, |owner| *owner);
        Self::for_tools(owner, |name| {
            step.tool_router.exposes_tool(&ToolName::plain(name))
        })
    }

    fn for_tools(owner: InferenceCompletionPolicy, exposed: impl Fn(&str) -> bool) -> Self {
        if owner != InferenceCompletionPolicy::HostTool
            || !exposed("context_read")
            || !exposed("context_material_read")
        {
            return Self::default();
        }
        let mut guidance = String::from(
            "Your LAX role, accepted work, goals/plans, evidence and pending communication are durable Hollywood material. Use `context_read` for authorized references and `context_material_read` for the exact current records after a context boundary. A finished inference or reset does not complete accepted Work or publish a response. ",
        );
        if exposed("context_selection") && exposed("retain_context_input") {
            guidance.push_str(
                "Use `context_selection` and `retain_context_input` to select durable references for reconstruction. Current role and captured obligations remain authoritative independently of selected historical facts. ",
            );
        }
        if exposed("request_context_rebuild") {
            guidance.push_str(
                "Use `request_context_rebuild` when a fresh window is needed; it yields this inference through the installed lifecycle and reconstructs from canonical state without a model summary. ",
            );
        }
        if exposed("context_action_read") {
            guidance.push_str(
                "Use `context_action_read` for original native action receipts referenced by your work. ",
            );
        }
        if exposed("context_writer_evidence_read") {
            guidance.push_str(
                "Use `context_writer_evidence_read` for authorized original Writer receipts; follow its exact index/chunk references. ",
            );
        }
        guidance.push_str(
            "Execution-local store/load values may disappear after a process restart. Preserve needed facts in durable work evidence, artifact references and retained material. Reconcile original uncertain operations instead of replaying effects because local context or store values are missing.",
        );
        Self {
            guidance: Some(guidance),
            reminder: Some(
                "Only {n_remaining} tokens remain in this window. Follow the installed LAX context-material and reconstruction contract. Accepted Work, goals/plans and original operation receipts remain durable; a context boundary is not completion.",
            ),
            fallback: Some(
                "This context window is exhausted. Use the installed LAX context reconstruction lifecycle and restore exact current material through its exposed tools. Preserve the accepted objective, evidence, pending communication and unknown original operations. Do not infer Work completion or replay an effect from lost local context.",
            ),
        }
    }
}

#[cfg(test)]
#[path = "lax_context_contract_tests.rs"]
mod tests;
