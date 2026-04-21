use crate::hollywood::HollywoodEnvironmentContext;
use crate::hollywood::HollywoodSemanticContext;
use crate::session::turn_context::TurnContext;
use crate::shell::Shell;
use codex_protocol::protocol::TurnContextItem;
use codex_protocol::protocol::TurnContextNetworkItem;
use std::path::PathBuf;

use super::ContextualUserFragment;

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct EnvironmentContext {
    pub(crate) cwd: Option<PathBuf>,
    pub(crate) shell: String,
    pub(crate) current_date: Option<String>,
    pub(crate) timezone: Option<String>,
    pub(crate) network: Option<NetworkContext>,
    pub(crate) subagents: Option<String>,
    pub(crate) hollywood: Option<HollywoodEnvironmentContext>,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub(crate) struct NetworkContext {
    allowed_domains: Vec<String>,
    denied_domains: Vec<String>,
}

impl NetworkContext {
    pub(crate) fn new(allowed_domains: Vec<String>, denied_domains: Vec<String>) -> Self {
        Self {
            allowed_domains,
            denied_domains,
        }
    }
}

impl EnvironmentContext {
    pub(crate) fn new(
        cwd: Option<PathBuf>,
        shell: String,
        current_date: Option<String>,
        timezone: Option<String>,
        network: Option<NetworkContext>,
        subagents: Option<String>,
        hollywood: Option<HollywoodEnvironmentContext>,
    ) -> Self {
        Self {
            cwd,
            shell,
            current_date,
            timezone,
            network,
            subagents,
            hollywood,
        }
    }

    /// Compares two environment contexts, ignoring the shell. Useful when
    /// comparing turn to turn, since the initial environment_context will
    /// include the shell, and then it is not configurable from turn to turn.
    pub(crate) fn equals_except_shell(&self, other: &EnvironmentContext) -> bool {
        let EnvironmentContext {
            cwd,
            current_date,
            timezone,
            network,
            subagents,
            hollywood,
            shell: _,
        } = other;
        self.cwd == *cwd
            && self.current_date == *current_date
            && self.timezone == *timezone
            && self.network == *network
            && self.subagents == *subagents
            && self.hollywood == *hollywood
    }

    pub(crate) fn diff_from_turn_context_item(
        before: &TurnContextItem,
        after: &EnvironmentContext,
    ) -> Self {
        let before_network = Self::network_from_turn_context_item(before);
        let cwd = match &after.cwd {
            Some(cwd) if before.cwd.as_path() != cwd.as_path() => Some(cwd.clone()),
            _ => None,
        };
        let network = if before_network != after.network {
            after.network.clone()
        } else {
            before_network
        };
        EnvironmentContext::new(
            cwd,
            after.shell.clone(),
            after.current_date.clone(),
            after.timezone.clone(),
            network,
            /*subagents*/ None,
            /*hollywood*/ None,
        )
    }

    pub(crate) fn from_turn_context(turn_context: &TurnContext, shell: &Shell) -> Self {
        Self::new(
            Some(turn_context.cwd.to_path_buf()),
            shell.name().to_string(),
            turn_context.current_date.clone(),
            turn_context.timezone.clone(),
            Self::network_from_turn_context(turn_context),
            /*subagents*/ None,
            /*hollywood*/ None,
        )
    }

    pub(crate) fn from_turn_context_item(
        turn_context_item: &TurnContextItem,
        shell: String,
    ) -> Self {
        Self::new(
            Some(turn_context_item.cwd.clone()),
            shell,
            turn_context_item.current_date.clone(),
            turn_context_item.timezone.clone(),
            Self::network_from_turn_context_item(turn_context_item),
            /*subagents*/ None,
            /*hollywood*/ None,
        )
    }

    pub(crate) fn with_subagents(mut self, subagents: String) -> Self {
        if !subagents.is_empty() {
            self.subagents = Some(subagents);
        }
        self
    }

    pub(crate) fn with_hollywood(mut self, hollywood: Option<HollywoodEnvironmentContext>) -> Self {
        self.hollywood = hollywood;
        self
    }

    fn network_from_turn_context(turn_context: &TurnContext) -> Option<NetworkContext> {
        let network = turn_context
            .config
            .config_layer_stack
            .requirements()
            .network
            .as_ref()?;

        Some(NetworkContext::new(
            network
                .domains
                .as_ref()
                .and_then(codex_config::NetworkDomainPermissionsToml::allowed_domains)
                .unwrap_or_default(),
            network
                .domains
                .as_ref()
                .and_then(codex_config::NetworkDomainPermissionsToml::denied_domains)
                .unwrap_or_default(),
        ))
    }

    fn network_from_turn_context_item(
        turn_context_item: &TurnContextItem,
    ) -> Option<NetworkContext> {
        let TurnContextNetworkItem {
            allowed_domains,
            denied_domains,
        } = turn_context_item.network.as_ref()?;
        Some(NetworkContext::new(
            allowed_domains.clone(),
            denied_domains.clone(),
        ))
    }
}

impl ContextualUserFragment for EnvironmentContext {
    const ROLE: &'static str = "user";
    const START_MARKER: &'static str = codex_protocol::protocol::ENVIRONMENT_CONTEXT_OPEN_TAG;
    const END_MARKER: &'static str = codex_protocol::protocol::ENVIRONMENT_CONTEXT_CLOSE_TAG;

    fn body(&self) -> String {
        self.clone().serialize_to_xml()
    }
}

fn append_hollywood_context_lines(
    lines: &mut Vec<String>,
    semantic: HollywoodSemanticContext,
    tools: Vec<String>,
) {
    lines.push("  <hollywood>".to_string());
    lines.push(format!("    <attached>{}</attached>", semantic.attached));
    lines.push(format!("    <url>{}</url>", semantic.url));
    lines.push(format!("    <room>{}</room>", semantic.room));
    lines.push(format!(
        "    <attention_mode>{}</attention_mode>",
        semantic.attention_mode
    ));
    lines.push("    <identities>".to_string());
    for identity in semantic.identities {
        lines.push(format!("      <identity>{identity}</identity>"));
    }
    lines.push("    </identities>".to_string());
    lines.push("    <tools>".to_string());
    for tool in tools {
        lines.push(format!("      <tool>{tool}</tool>"));
    }
    lines.push("    </tools>".to_string());
    lines.push("  </hollywood>".to_string());
}

impl EnvironmentContext {
    /// Serializes the environment context to XML. Libraries like `quick-xml`
    /// require custom macros to handle Enums with newtypes, so we just do it
    /// manually, to keep things simple. Output looks like:
    ///
    /// ```xml
    /// <environment_context>
    ///   <cwd>...</cwd>
    ///   <shell>...</shell>
    /// </environment_context>
    /// ```
    pub fn serialize_to_xml(self) -> String {
        let mut lines = Vec::new();
        if let Some(cwd) = &self.cwd {
            lines.push(format!("  <cwd>{}</cwd>", cwd.to_string_lossy()));
        }

        lines.push(format!("  <shell>{}</shell>", self.shell));
        if let Some(current_date) = &self.current_date {
            lines.push(format!("  <current_date>{current_date}</current_date>"));
        }
        if let Some(timezone) = &self.timezone {
            lines.push(format!("  <timezone>{timezone}</timezone>"));
        }
        if let Some(network) = &self.network {
            lines.push("  <network enabled=\"true\">".to_string());
            for allowed in &network.allowed_domains {
                lines.push(format!("    <allowed>{allowed}</allowed>"));
            }
            for denied in &network.denied_domains {
                lines.push(format!("    <denied>{denied}</denied>"));
            }
            lines.push("  </network>".to_string());
        }
        if let Some(subagents) = &self.subagents {
            lines.push("  <subagents>".to_string());
            lines.extend(subagents.lines().map(|line| format!("    {line}")));
            lines.push("  </subagents>".to_string());
        }
        if let Some(hollywood) = self.hollywood {
            let HollywoodEnvironmentContext { semantic, runtime } = hollywood;
            append_hollywood_context_lines(&mut lines, semantic, runtime.tools);
        }
        format!("\n{}\n", lines.join("\n"))
    }
}

#[cfg(test)]
#[path = "environment_context_tests.rs"]
mod tests;
