//! Canonical enterprise collaboration over an authenticated protected native RPC.
//! Standalone tools retain private state; enterprise failures never fall back to it.
use crate::function_tool::FunctionCallError;
use crate::tools::context::ToolInvocation;
use crate::tools::sandboxing::ToolCtx;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

pub(crate) const FRAME_LIMIT: usize = 1024 * 1024;
const CHANNEL_ENV: &str = "LAX_CANONICAL_NATIVE_CHANNEL";

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct Channel {
    pub schema: String,
    pub socket: PathBuf,
    pub ports: BTreeSet<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Call<'a> {
    schema: &'static str,
    thread_id: String,
    turn_id: &'a str,
    call_id: &'a str,
    tool: &'a str,
    port: &'a str,
    arguments: Value,
    evidence: Option<Value>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct Reply {
    pub success: bool,
    pub result: Value,
    pub canonical_receipt: Option<Value>,
    pub hold_reason: Option<String>,
}

pub(crate) fn enterprise() -> bool {
    std::env::var_os(CHANNEL_ENV).is_some()
        || std::env::var("LAX_NATIVE_ENTERPRISE").is_ok_and(|value| value == "1")
}

fn held(message: impl std::fmt::Display) -> FunctionCallError {
    FunctionCallError::RespondToModel(format!(
        "Canonical collaboration held: {message}; no local authority fallback or automatic retry"
    ))
}

#[cfg(unix)]
fn protected_path(path: &Path, socket: bool) -> std::io::Result<()> {
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;
    if !path.is_absolute() {
        return Err(std::io::Error::other(
            "absolute protected channel path required",
        ));
    }
    for parent in path.ancestors().skip(1) {
        let metadata = std::fs::symlink_metadata(parent)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(std::io::Error::other(
                "channel ancestor is not administrator protected",
            ));
        }
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.uid() != 0
        || metadata.file_type().is_symlink()
        || if socket {
            !metadata.file_type().is_socket()
        } else {
            !metadata.is_file() || metadata.mode() & 0o022 != 0
        }
    {
        return Err(std::io::Error::other(
            "channel endpoint is not administrator protected",
        ));
    }
    Ok(())
}

#[cfg(unix)]
pub(crate) fn channel() -> Result<Channel, FunctionCallError> {
    use std::io::Read;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    let path = std::env::var_os(CHANNEL_ENV)
        .ok_or_else(|| held("protected channel installation missing"))?;
    let path = PathBuf::from(path);
    protected_path(&path, false).map_err(held)?;
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&path)
        .map_err(held)?;
    let metadata = file.metadata().map_err(held)?;
    if metadata.uid() != 0 || metadata.mode() & 0o022 != 0 || metadata.len() > 65_536 {
        return Err(held("channel descriptor changed"));
    }
    let mut bytes = Vec::new();
    file.take(65_537).read_to_end(&mut bytes).map_err(held)?;
    if bytes.len() > 65_536 {
        return Err(held("channel descriptor too large"));
    }
    let channel: Channel = serde_json::from_slice(&bytes).map_err(held)?;
    if channel.schema != "lax-native-collaboration-channel/v1" {
        return Err(held("channel protocol differs"));
    }
    protected_path(&channel.socket, true).map_err(held)?;
    Ok(channel)
}

#[cfg(not(unix))]
pub(crate) fn channel() -> Result<Channel, FunctionCallError> {
    Err(held(
        "protected native transport is unavailable on this platform",
    ))
}

pub(crate) fn implements(port: &str) -> bool {
    enterprise() && channel().is_ok_and(|channel| channel.ports.contains(port))
}

pub(crate) async fn invocation(
    invocation: &ToolInvocation,
    port: &str,
    arguments: Value,
) -> Result<Value, FunctionCallError> {
    let environment = invocation
        .step_context
        .environments
        .primary()
        .ok_or_else(|| held("captured primary environment unavailable"))?;
    let evidence = serde_json::json!({"environmentId":environment.selection.environment_id,"cwd":environment.cwd().to_string()});
    invoke(
        invocation.session.thread_id().to_string(),
        &invocation.turn.sub_id,
        &invocation.call_id,
        &invocation.tool_name.name,
        port,
        arguments,
        Some(evidence),
    )
    .await
}

pub(crate) async fn tool_context(
    ctx: &ToolCtx,
    port: &str,
    arguments: Value,
) -> Result<Value, FunctionCallError> {
    invoke(
        ctx.session.thread_id().to_string(),
        &ctx.step_context.turn.sub_id,
        &ctx.call_id,
        &ctx.tool_name.name,
        port,
        arguments,
        None,
    )
    .await
}

async fn invoke(
    thread_id: String,
    turn_id: &str,
    call_id: &str,
    tool: &str,
    port: &str,
    arguments: Value,
    evidence: Option<Value>,
) -> Result<Value, FunctionCallError> {
    let channel = channel()?;
    if !channel.ports.contains(port) {
        return Err(held(format!(
            "native port {port} is not implemented/enrolled"
        )));
    }
    let request = Call {
        schema: "lax-native-collaboration-rpc/v1",
        thread_id,
        turn_id,
        call_id,
        tool,
        port,
        arguments,
        evidence,
    };
    let wire = serde_json::to_vec(&request).map_err(held)?;
    if wire.len() > FRAME_LIMIT {
        return Err(held("native callback exceeds frame bound"));
    }
    let response = tokio::time::timeout(
        std::time::Duration::from_secs(30),
        exchange(&channel.socket, &wire),
    )
    .await
    .map_err(|_| held("original callback outcome unknown after channel deadline"))?
    .map_err(held)?;
    let reply: Reply = serde_json::from_slice(&response).map_err(held)?;
    if !reply.success {
        return Err(held(
            reply
                .hold_reason
                .unwrap_or_else(|| "bridge rejected current effect".to_string()),
        ));
    }
    if reply.canonical_receipt.is_none() {
        return Err(held("bridge returned no canonical receipt"));
    }
    Ok(serde_json::json!({"result": reply.result, "canonicalReceipt": reply.canonical_receipt}))
}

#[cfg(unix)]
async fn exchange(path: &Path, wire: &[u8]) -> std::io::Result<Vec<u8>> {
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    let mut stream = tokio::net::UnixStream::connect(path).await?;
    if stream.peer_cred()?.uid() != 0 {
        return Err(std::io::Error::other(
            "native bridge peer is not administrator",
        ));
    }
    stream.write_u32(wire.len() as u32).await?;
    stream.write_all(wire).await?;
    let len = stream.read_u32().await? as usize;
    if len == 0 || len > FRAME_LIMIT {
        return Err(std::io::Error::other("invalid native reply bound"));
    }
    let mut bytes = vec![0; len];
    stream.read_exact(&mut bytes).await?;
    Ok(bytes)
}
#[cfg(not(unix))]
async fn exchange(_path: &Path, _wire: &[u8]) -> std::io::Result<Vec<u8>> {
    Err(std::io::Error::other(
        "protected native channel unavailable",
    ))
}

/// Model schemas contain intent only. Protected identity is absent from tool arguments.
pub(crate) fn specification(name: &str) -> codex_tools::ToolSpec {
    let (schema, description) = if name == "collaborative_edit_plan" {
        (
            include_str!("canonical_collaboration/edit_plan.schema.json"),
            "Create, revise and explicitly consent to a canonical revision/content-bound edit plan for admitted work. Participants, integrator and physical source mapping are canonical. Compute patchSha256 from the exact UTF-8 PATCH argument passed to apply_patch, including a final newline when present. This tool cannot issue a mutation grant; apply_patch obtains its own one-shot preflight/begin/settlement.",
        )
    } else {
        (
            include_str!("canonical_collaboration/path_claim.schema.json"),
            "Record canonical physical path ownership for already admitted work, with revision/content expectations, explicit reviewed release or offered/accepted handoff. Expiry and unknown effects retain ownership. Claim inspection never grants permission to patch.",
        )
    };
    let input: Value =
        serde_json::from_str(schema).expect("reviewed canonical native intent schema");
    let parameters = codex_tools::parse_tool_input_schema_without_compaction(&input)
        .expect("valid reviewed native intent schema");
    codex_tools::ToolSpec::Function(codex_tools::ResponsesApiTool {
        name: name.to_string(),
        description: description.to_string(),
        strict: false,
        defer_loading: None,
        output_schema: None,
        parameters,
    })
}

/// Patch phases retain the same original native argument digest and call identity.
pub(crate) async fn patch_call(
    ctx: &ToolCtx,
    port: &str,
    patch: &str,
    mut evidence: Value,
) -> Result<Value, FunctionCallError> {
    evidence["originTool"] = Value::String(ctx.tool_name.name.clone());
    invoke(
        ctx.session.thread_id().to_string(),
        &ctx.step_context.turn.sub_id,
        &ctx.call_id,
        "apply_patch",
        port,
        Value::String(patch.to_string()),
        Some(evidence),
    )
    .await
}
