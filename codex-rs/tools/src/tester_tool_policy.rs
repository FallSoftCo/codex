use codex_protocol::protocol::SessionSource;
use std::collections::BTreeSet;

const TESTER_SESSION_SOURCE_PREFIX: &str = "tester";

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
        if source == TESTER_SESSION_SOURCE_PREFIX {
            return Some(Self::default());
        }
        let Some(rest) = source.strip_prefix("tester:") else {
            return None;
        };
        let allowed_interfaces = rest
            .split(',')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(|value| value.to_string())
            .collect();
        Some(Self { allowed_interfaces })
    }

    pub fn allows_terminal_harness(&self) -> bool {
        self.allowed_interfaces.contains("terminal_harness")
    }
}
