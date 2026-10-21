//! Preserve programmatic tool data without injecting a giant automatic model item.
use crate::tools::context::FunctionToolOutput;
use codex_protocol::models::ResponseInputItem;
use codex_tools::ToolOutput;
use codex_tools::ToolPayload;
use serde_json::Value;

pub(super) struct DynamicToolOutput {
    pub(super) model: FunctionToolOutput,
    pub(super) code_mode_text: Option<String>,
}

impl ToolOutput for DynamicToolOutput {
    fn log_output(&self) -> String {
        self.model.log_output()
    }

    fn success_for_logging(&self) -> bool {
        self.model.success_for_logging()
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        self.model.to_response_item(call_id, payload)
    }

    fn code_mode_result(&self, payload: &ToolPayload) -> Value {
        match &self.code_mode_text {
            Some(text) => Value::String(text.clone()),
            None => self.model.code_mode_result(payload),
        }
    }

    fn post_tool_use_response(&self, call_id: &str, payload: &ToolPayload) -> Option<Value> {
        self.model.post_tool_use_response(call_id, payload)
    }
}
