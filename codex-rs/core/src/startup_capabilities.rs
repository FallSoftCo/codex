use crate::config::Config;
use crate::tools::js_repl::resolve_compatible_node;
use codex_features::Feature;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct StartupCapabilities {
    pub(crate) js_repl_available: bool,
    pub(crate) startup_warnings: Vec<String>,
}

impl Default for StartupCapabilities {
    fn default() -> Self {
        Self {
            js_repl_available: true,
            startup_warnings: Vec::new(),
        }
    }
}

impl StartupCapabilities {
    pub(crate) async fn detect(config: &Config) -> Self {
        let mut capabilities = Self {
            js_repl_available: true,
            startup_warnings: Vec::new(),
        };

        if config.features.enabled(Feature::JsRepl)
            && let Err(err) = resolve_compatible_node(config.js_repl_node_path.as_deref()).await
        {
            capabilities.js_repl_available = false;
            capabilities.startup_warnings.push(format!(
                "Disabled `js_repl` for this session because the configured Node runtime is unavailable or incompatible. {err}"
            ));
        }

        capabilities
    }
}
