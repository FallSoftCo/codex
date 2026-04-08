use codex_protocol::protocol::SessionSource;
use std::collections::BTreeSet;

const LEGACY_TESTER_SESSION_SOURCE_PREFIX: &str = "tester";

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TesterToolPolicy {
    allowed_interfaces: BTreeSet<String>,
}

impl TesterToolPolicy {
    pub fn from_session_source(session_source: &SessionSource) -> Option<Self> {
        let SessionSource::Custom(source) = session_source else {
            return None;
        };
        let source = source.trim();
        if source == LEGACY_TESTER_SESSION_SOURCE_PREFIX {
            return Some(Self::default());
        }
        if let Some(rest) = source.strip_prefix("tester:") {
            let allowed_interfaces = rest
                .split(',')
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(std::string::ToString::to_string)
                .collect();
            return Some(Self { allowed_interfaces });
        }
        let rest = source.strip_prefix("tester_run:")?;
        let mut parts = rest.splitn(2, ':');
        let _execution_class = parts.next();
        let allowed_interfaces = parts
            .next()
            .unwrap_or_default()
            .split(',')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(std::string::ToString::to_string)
            .collect();
        Some(Self { allowed_interfaces })
    }

    pub fn allows_terminal_harness(&self) -> bool {
        self.allowed_interfaces.contains("terminal_harness")
    }
}
