//! A startup ceiling on tool selection and construction, independent of session identity.
//! This policy only restricts tools; permission and approval checks still apply.

use crate::ToolName;

/// Supply through `ExtensionDataInit` before starting a thread. The host captures
/// the policy once; later extension-state changes cannot relax it. Callers must
/// supply it again when resuming a thread.
#[derive(Clone, Debug)]
pub struct ToolPolicy {
    /// `None` keeps ordinary tool selection; an empty list permits no tools.
    /// Names include their namespace; plain names use the default namespace.
    /// Generated tools such as Code Mode's `exec` and `wait` must also be listed.
    pub allowed_tools: Option<Vec<ToolName>>,
    /// Omit core tools unless the thread and every ready environment use a managed sandbox.
    pub require_managed_sandbox: bool,
    /// Omit shell tools when unified exec is disabled, instead of using one-shot exec.
    pub require_unified_exec: bool,
    /// Advertise additional-permission arguments when the feature is enabled.
    pub expose_additional_permissions: bool,
}

impl Default for ToolPolicy {
    fn default() -> Self {
        Self {
            allowed_tools: None,
            require_managed_sandbox: false,
            require_unified_exec: false,
            expose_additional_permissions: true,
        }
    }
}

/// An additional host ceiling. It is intersected with the base startup policy,
/// including reviewer requirements, and must be supplied again on cold resume.
#[derive(Clone, Debug)]
pub struct AdditionalToolAllowlist(pub Vec<ToolName>);

impl ToolPolicy {
    pub fn restricted_to(&self, allowed: &[ToolName]) -> Self {
        let mut policy = self.clone();
        policy.allowed_tools = Some(
            allowed
                .iter()
                .filter(|name| self.allows(name))
                .cloned()
                .collect(),
        );
        policy
    }

    pub fn allows(&self, tool: &ToolName) -> bool {
        self.allowed_tools.as_ref().is_none_or(|tools| {
            tools.iter().any(|allowed| {
                allowed.name == tool.name
                    && (allowed.namespace == tool.namespace
                        || (allowed.is_default_namespace() && tool.is_default_namespace()))
            })
        })
    }
}

#[cfg(test)]
mod tests {
    use super::ToolPolicy;
    use crate::ToolName;

    #[test]
    fn additional_allowlist_preserves_base_ceiling_and_requirements() {
        let base = ToolPolicy {
            allowed_tools: Some(vec![ToolName::plain("inspect")]),
            require_managed_sandbox: true,
            require_unified_exec: true,
            expose_additional_permissions: false,
        };
        let restricted = base.restricted_to(&[
            ToolName::namespaced("functions", "inspect"),
            ToolName::plain("exec_command"),
        ]);
        assert!(restricted.allows(&ToolName::plain("inspect")));
        assert!(!restricted.allows(&ToolName::plain("exec_command")));
        assert!(!restricted.allows(&ToolName::namespaced("foreign", "inspect")));
        assert!(restricted.require_managed_sandbox);
        assert!(restricted.require_unified_exec);
        assert!(!restricted.expose_additional_permissions);
        assert!(base.allows(&ToolName::plain("inspect")));
        assert!(!base.restricted_to(&[]).allows(&ToolName::plain("inspect")));
    }
}
