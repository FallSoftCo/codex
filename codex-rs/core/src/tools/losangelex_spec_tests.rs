use super::create_hollywood_send_tool;
use codex_tools::ToolSpec;

#[test]
fn hollywood_send_tool_discourages_duplicate_required_asks() {
    let ToolSpec::Function(tool) = create_hollywood_send_tool(/*state_db_available*/ false) else {
        panic!("hollywood_send should be a function tool");
    };

    assert!(tool.description.contains("one pending ask"));
    assert!(tool.description.contains("do not send a duplicate nudge"));

    let response_policy = tool
        .parameters
        .properties
        .as_ref()
        .expect("object properties")
        .get("response_policy")
        .expect("response_policy parameter");
    let description = response_policy
        .description
        .as_deref()
        .expect("response_policy description");
    assert!(description.contains("one pending ask"));
    assert!(description.contains("do not send duplicate nudges"));
}
