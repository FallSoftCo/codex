//! Canonical short patch permits around actual approved filesystem mutation.
use crate::canonical_collaboration;
use crate::function_tool::FunctionCallError;
use crate::tools::runtimes::apply_patch::ApplyPatchRequest;
use crate::tools::sandboxing::ToolCtx;
use codex_apply_patch::ApplyPatchFileChange;
use codex_apply_patch::MaybeApplyPatchVerified;
use codex_exec_server::FileSystemSandboxContext;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;

/// File-content result only; the protected bridge independently observes every
/// original path before deciding whether a failed operation may settle.
pub(crate) enum PatchOutcome {
    Applied,
    NotApplied,
    Unknown,
}

pub(crate) struct PatchPermit {
    evidence: Value,
}
fn held(message: impl std::fmt::Display) -> FunctionCallError {
    FunctionCallError::RespondToModel(format!(
        "Canonical patch held: {message}; inspect/reconcile the original operation before another mutation"
    ))
}
fn content(value: &str) -> Value {
    json!({"sha256": format!("{:x}", Sha256::digest(value.as_bytes())), "size": value.len()})
}
fn absent() -> Value {
    json!({"sha256":"absent", "size":0})
}

impl PatchPermit {
    pub(crate) async fn reserve(
        req: &ApplyPatchRequest,
        ctx: &ToolCtx,
        sandbox: Option<&FileSystemSandboxContext>,
    ) -> Result<Option<Self>, FunctionCallError> {
        if !canonical_collaboration::enterprise() {
            return Ok(None);
        }
        if req.turn_environment.environment.is_remote() {
            return Err(held(
                "selected remote environment has no implemented protected mutation bridge",
            ));
        }
        for port in ["patch-preflight", "patch-begin", "patch-settle"] {
            if !canonical_collaboration::implements(port) {
                return Err(held(format!("protected {port} port unavailable")));
            }
        }
        let fs = req.turn_environment.environment.get_filesystem();
        // Re-verify after the orchestrator's approval wait, preserving all modern filesystem/sandbox routing.
        let args = codex_apply_patch::parse_patch(&req.action.patch).map_err(held)?;
        let fresh =
            codex_apply_patch::verify_apply_patch_args(args, &req.action.cwd, fs.as_ref(), sandbox)
                .await;
        if !matches!(fresh, MaybeApplyPatchVerified::Body(ref action) if action == &req.action) {
            return Err(held(
                "source changed after verified/approved patch; reread/rebase and obtain new consent",
            ));
        }
        let mut files = Vec::new();
        for (path, change) in req.action.changes() {
            let before = match fs.read_file_text(path, Default::default(), sandbox).await {
                Ok(text) => content(&text),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => absent(),
                Err(error) => return Err(held(error)),
            };
            let after = match change {
                ApplyPatchFileChange::Add { content: text } => content(text),
                ApplyPatchFileChange::Delete { .. } => absent(),
                ApplyPatchFileChange::Update { new_content, .. } => content(new_content),
            };
            if let ApplyPatchFileChange::Update {
                move_path: Some(target),
                ..
            } = change
            {
                if target != path {
                    let target_before =
                        match fs.read_file_text(target, Default::default(), sandbox).await {
                            Ok(text) => content(&text),
                            Err(error) if error.kind() == std::io::ErrorKind::NotFound => absent(),
                            Err(error) => return Err(held(error)),
                        };
                    files.push(json!({"pathUri":target.to_string(),"beforeSha256":target_before["sha256"],"beforeSize":target_before["size"],"afterSha256":after["sha256"],"afterSize":after["size"]}));
                    files.push(json!({"pathUri":path.to_string(),"beforeSha256":before["sha256"],"beforeSize":before["size"],"afterSha256":"absent","afterSize":0}));
                    continue;
                }
            }
            files.push(json!({"pathUri":path.to_string(),"beforeSha256":before["sha256"],"beforeSize":before["size"],"afterSha256":after["sha256"],"afterSize":after["size"]}));
        }
        files.sort_by(|a, b| a["pathUri"].as_str().cmp(&b["pathUri"].as_str()));
        let evidence =
            json!({"environmentId":req.turn_environment.selection.environment_id,"files":files});
        canonical_collaboration::patch_call(
            ctx,
            "patch-preflight",
            &req.action.patch,
            evidence.clone(),
        )
        .await?;
        let begin = canonical_collaboration::patch_call(
            ctx,
            "patch-begin",
            &req.action.patch,
            evidence.clone(),
        )
        .await?;
        let admission = &begin["result"]["admission"];
        if begin["result"]["replayed"] != false
            || admission["mayApply"] != true
            || admission["oneShotOriginalResponseOnly"] != true
        {
            return Err(held(
                "receipt/replay is not an original one-shot apply grant",
            ));
        }
        let expiry = admission["expiresAt"]
            .as_str()
            .ok_or_else(|| held("grant expiry missing"))?;
        let expires = chrono::DateTime::parse_from_rfc3339(expiry).map_err(held)?;
        if expires <= chrono::Utc::now() {
            return Err(held("mutation grant already expired"));
        }
        if admission["patchSha256"] != format!("{:x}", Sha256::digest(req.action.patch.as_bytes()))
        {
            return Err(held("grant patch digest differs"));
        }
        Ok(Some(Self { evidence }))
    }

    pub(crate) async fn settle(
        self,
        req: &ApplyPatchRequest,
        ctx: &ToolCtx,
        outcome: PatchOutcome,
    ) -> Result<(), FunctionCallError> {
        let mut evidence = self.evidence;
        evidence["outcome"] = match outcome {
            PatchOutcome::Applied => json!("applied"),
            PatchOutcome::NotApplied => json!("notApplied"),
            PatchOutcome::Unknown => json!("unknown"),
        };
        let reply =
            canonical_collaboration::patch_call(ctx, "patch-settle", &req.action.patch, evidence)
                .await?;
        // A held/unknown settlement is durable evidence, not successful completion or retry permission.
        if reply["result"]["settlementState"] != "settled" {
            return Err(held(
                "observed mutation settlement remains held/unconfirmed",
            ));
        }
        Ok(())
    }
}
