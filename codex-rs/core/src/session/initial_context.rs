//! Initial native context has an explicit acquisition boundary.
//! Acquisition owns both service collection and world/fragment callbacks.
//! The renderer takes only an owned, serializable template and target metadata.
//! This boundary alone does not enable idle acquisition or persist a new seed.
use super::*;
use crate::state::AutoCompactWindowIds;
use codex_context_fragments::AnnotatedContent;
use codex_protocol::AgentPath;

/// Annotated non-world source material from one explicit collection.
/// Window IDs are not cached: rendering always uses its caller's target IDs.
#[derive(Clone)]
pub(super) struct InitialContextMaterial {
    developer_sections: Vec<RenderedFragment>,
    turn_sections: Vec<RenderedFragment>,
    context_window_hints: Vec<AnnotatedContent>,
    token_budget_path: Option<AgentPath>,
    recommended_plugins: Option<RenderedFragment>,
    guardian_message: Option<ResponseItem>,
}

/// An inert complete initial-context recipe. No erased sections, closures or
/// extension handles cross this boundary. Window metadata remains typed, not
/// captured text to search/replace. Persistence and freshness admission are
/// separate from this data representation.
#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct InitialContextTemplate {
    prefix: Vec<ResponseItem>,
    items: Vec<ResponseItem>,
    pub(super) snapshot: WorldStateSnapshot,
    window: Option<CapturedWindowContext>,
}

#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct CapturedWindowContext {
    index: usize,
    agent_path: AgentPath,
    // An annotated message is the existing owned wire carrier for hint parts.
    hints: ResponseItem,
}

impl Session {
    pub(super) async fn collect_initial_context(
        &self,
        step_context: &StepContext,
    ) -> InitialContextMaterial {
        let turn_context = step_context.turn.as_ref();
        let mut developer_sections = Vec::<RenderedFragment>::with_capacity(8);
        let mut token_budget_path = None;
        let mut context_window_hints = Vec::new();
        let session_source = self
            .state
            .lock()
            .await
            .session_configuration
            .session_source
            .clone();
        let separate_guardian_developer_message =
            crate::guardian::is_basic_session_source(&session_source);
        // Keep the guardian policy prompt out of the aggregated developer bundle so it
        // stays isolated as its own top-level developer message for guardian subagents.
        if !separate_guardian_developer_message
            && let Some(developer_instructions) = turn_context.developer_instructions.as_deref()
            && !developer_instructions.is_empty()
        {
            developer_sections
                .push(DeveloperInstructions::new(developer_instructions).render_fragment());
        }
        let loaded_plugins = self
            .services
            .plugins_manager
            .plugins_for_config(&turn_context.config.plugins_config_input())
            .await
            .without_plugins(&turn_context.disabled_plugin_ids);
        let recommended_plugin_candidates = if turn_context
            .config
            .features
            .plugin_recommendations_enabled()
        {
            let auth = self.services.auth_manager.auth().await;
            let plugins_config = turn_context.config.plugins_config_input();
            self.services
                .plugins_manager
                .recommended_plugin_candidates_for_config(RecommendedPluginCandidatesInput {
                    plugins_config: &plugins_config,
                    loaded_plugins: &loaded_plugins,
                    auth: auth.as_ref(),
                    disabled_tools: &turn_context.config.tool_suggest.disabled_tools,
                    app_server_client_name: turn_context.app_server_client_name.as_deref(),
                })
                .await
        } else {
            None
        };
        let context_contributors = self.services.extensions.context_contributors().to_vec();
        for contributor in &context_contributors {
            for fragment in contributor
                .contribute_thread_context(
                    &self.services.session_extension_data,
                    &self.services.thread_extension_data,
                )
                .await
            {
                match fragment.slot() {
                    PromptSlot::ContextWindow => {
                        context_window_hints.push(fragment.into_content());
                    }
                    PromptSlot::DeveloperPolicy | PromptSlot::DeveloperCapabilities => {
                        developer_sections.push(fragment.into());
                    }
                }
            }
        }
        let mut turn_sections = Vec::new();
        for contributor in &context_contributors {
            for fragment in contributor
                .contribute_turn_context(TurnContextContributionInput {
                    thread_id: self.thread_id(),
                    turn_id: turn_context.sub_id.as_str(),
                    session_store: &self.services.session_extension_data,
                    thread_store: &self.services.thread_extension_data,
                    turn_store: turn_context.extension_data.as_ref(),
                    model_context_window: step_context.settings.model_info.usable_context_window(),
                })
                .await
            {
                turn_sections.push(fragment.into());
            }
        }
        // This is full-context metadata. Steady-state context diffs should not re-emit it.
        if turn_context.config.features.enabled(Feature::TokenBudget)
            && step_context
                .settings
                .model_info
                .resolved_context_window()
                .is_some()
        {
            // Keep the legacy bridge hint when native Notes is disabled. A failed
            // native request must not fall back to the bridge.
            if !turn_context
                .config
                .token_budget
                .as_ref()
                .is_some_and(|config| config.use_history_notes_extension)
                && let Some((text, source_tool_namespace)) = self
                    .services
                    .mcp_runtime
                    .latest_call_tool(
                        "notes",
                        "thread_hint",
                        /*environment_id*/ None,
                        /*arguments*/ None,
                        Some(serde_json::json!({
                            "threadId": self.thread_id().to_string(),
                        })),
                        /*requested_timeout*/ None,
                        /*wait_for_server*/ true,
                    )
                    .await
                    .ok()
                    .and_then(|call| {
                        let text = call
                            .result
                            .content
                            .iter()
                            .filter_map(|content| {
                                content.get("text").and_then(serde_json::Value::as_str)
                            })
                            .filter(|text| !text.is_empty())
                            .collect::<Vec<_>>()
                            .join("\n");
                        (!text.is_empty()).then_some((text, call.source_tool_namespace))
                    })
            {
                context_window_hints.push(codex_context_fragments::AnnotatedContent::text(
                    text,
                    ContentItemKind("notes.thread_hint".to_string()),
                    ContentItemMetadata::tool(source_tool_namespace.map(Into::into)),
                ));
            }
            token_budget_path = Some(
                session_source
                    .get_agent_path()
                    .unwrap_or_else(codex_protocol::AgentPath::root),
            );
        }
        let guardian_message = if separate_guardian_developer_message {
            turn_context
                .developer_instructions
                .as_deref()
                .filter(|text| !text.is_empty())
                .and_then(|text| {
                    crate::context_manager::updates::build_rendered_message(vec![
                        GuardianPolicy::new(text).render_fragment(),
                    ])
                })
        } else {
            None
        };
        InitialContextMaterial {
            developer_sections,
            turn_sections,
            context_window_hints,
            token_budget_path,
            recommended_plugins: recommended_plugin_candidates
                .as_deref()
                .and_then(RecommendedPluginsInstructions::from_plugins)
                .map(|fragment| fragment.render_fragment()),
            guardian_message,
        }
    }
}

impl InitialContextMaterial {
    /// Reuse the same typed acquisition for steady-state emission and the
    /// complete producer. Stateful contributors must not be sampled twice.
    pub(super) fn turn_items(&self) -> Vec<ResponseItem> {
        crate::context_manager::updates::build_rendered_message(self.turn_sections.clone())
            .into_iter()
            .collect()
    }

    /// Execute all world/fragment callbacks during authorized acquisition, not
    /// during preview. Even an already-built WorldState can own live closures.
    pub(super) fn capture(&self, world_state: &WorldState) -> InitialContextTemplate {
        let mut developer_sections = self.developer_sections.clone();
        developer_sections.extend(self.turn_sections.clone());
        let mut contextual_user_sections = Vec::<RenderedFragment>::with_capacity(2);
        let mut separate_developer_messages = Vec::new();
        let mut window = None;
        let (snapshot, updates) = world_state.render_full();
        let (prefix, context) = split_prefix_updates(updates);
        let mut items = Vec::with_capacity(4);
        let mut context = context.into_iter();
        // Keep the initial-context grouping within each fragment run, but never across an item.
        loop {
            let mut next_item = None;
            // Render the active mode after the usage hint so it can override that hint.
            let mut initial_multi_agent_mode = None;
            let mut managed_developer_instructions = None;
            for update in context.by_ref() {
                let fragment = match update.content {
                    WorldStateUpdateContent::Fragment(fragment) => fragment,
                    WorldStateUpdateContent::Item(item) => {
                        next_item = Some(*item);
                        break;
                    }
                };
                match fragment.role() {
                    "developer"
                        if fragment.markers().0 == ModelSwitchInstructions::type_markers().0 =>
                    {
                        // New-model instructions must precede the rest of the developer context.
                        developer_sections.insert(0, fragment.render_fragment());
                    }
                    "developer" if fragment.markers().0 == MULTI_AGENT_MODE_OPEN_TAG => {
                        initial_multi_agent_mode = Some(fragment);
                    }
                    "developer"
                        if fragment.markers().0
                            == ManagedDeveloperInstructions::type_markers().0 =>
                    {
                        managed_developer_instructions = Some(fragment);
                    }
                    "developer"
                        if fragment.markers().0 == MultiAgentRoleInstructions::type_markers().0 =>
                    {
                        separate_developer_messages.push(fragment.render_fragment().into());
                    }
                    "developer"
                        if update.placement == Placement::Standalone
                            && fragment.markers().0.is_empty() =>
                    {
                        separate_developer_messages.push(fragment.render_fragment().into());
                    }
                    "developer" => developer_sections.push(fragment.render_fragment()),
                    "user" => contextual_user_sections.push(fragment.render_fragment()),
                    _ => {}
                }
            }

            if next_item.is_none()
                && let Some(fragment) = &self.recommended_plugins
            {
                developer_sections.push(fragment.clone());
            }

            if let Some(developer_message) = crate::context_manager::updates::build_rendered_message(
                std::mem::take(&mut developer_sections),
            ) {
                items.push(developer_message);
            }
            if window.is_none()
                && let Some(agent_path) = &self.token_budget_path
            {
                window = Some(CapturedWindowContext {
                    index: items.len(),
                    agent_path: agent_path.clone(),
                    hints: codex_context_fragments::message_from_parts(
                        "developer",
                        self.context_window_hints.clone(),
                    ),
                });
            }
            items.append(&mut separate_developer_messages);
            if let Some(initial_multi_agent_mode) = initial_multi_agent_mode
                && let Some(message) =
                    crate::context_manager::updates::build_rendered_message(vec![
                        initial_multi_agent_mode.render_fragment(),
                    ])
            {
                items.push(message);
            }
            if let Some(contextual_user_message) =
                crate::context_manager::updates::build_rendered_message(std::mem::take(
                    &mut contextual_user_sections,
                ))
            {
                items.push(contextual_user_message);
            }
            if next_item.is_none()
                && let Some(message) = &self.guardian_message
            {
                items.push(message.clone());
            }
            if let Some(managed_developer_instructions) = managed_developer_instructions
                && let Some(message) =
                    crate::context_manager::updates::build_rendered_message(vec![
                        managed_developer_instructions.render_fragment(),
                    ])
            {
                items.push(message);
            }

            if let Some(item) = next_item {
                items.push(item);
            } else {
                break;
            }
        }
        InitialContextTemplate {
            prefix,
            items,
            snapshot,
            window,
        }
    }
}

impl InitialContextTemplate {
    /// Pure replay from owned content only: no Session, WorldState, dynamic
    /// fragment, extension callback, service, filesystem or model handle.
    pub(super) fn render(
        &self,
        turn_id: &str,
        ids: AutoCompactWindowIds,
    ) -> std::io::Result<(Vec<WorldStateUpdate>, WorldStateSnapshot)> {
        if self.window.as_ref().is_some_and(|window| {
            window.index > self.items.len()
                || !matches!(&window.hints, ResponseItem::Message { role, .. } if role == "developer")
        }) {
            return Err(std::io::Error::other("invalid captured window metadata"));
        }
        let mut prefix = self.prefix.clone();
        let mut items = self.items.clone();
        if let Some(window) = &self.window {
            let mut hints = window.hints.clone();
            let hints = codex_context_fragments::to_annotated_content(&mut hints)
                .expect("captured window hints are an annotated message");
            items.insert(
                window.index,
                crate::context::TokenBudgetContext::new(
                    window.agent_path.clone(),
                    ids.first_window_id,
                    ids.previous_window_id,
                    ids.window_id,
                )
                .render_with_hints(hints),
            );
        }
        // New context windows install these items directly into replacement history.
        for item in prefix.iter_mut().chain(&mut items) {
            item.set_turn_id_if_missing(turn_id);
        }
        let updates = prefix
            .into_iter()
            .map(WorldStateUpdate::prefix_item)
            .chain(items.into_iter().map(|item| WorldStateUpdate {
                placement: Placement::Standalone,
                content: WorldStateUpdateContent::Item(Box::new(item)),
            }))
            .collect();
        Ok((updates, self.snapshot.clone()))
    }
}

#[cfg(test)]
#[path = "initial_context_tests.rs"]
mod tests;
