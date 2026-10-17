use crate::function_tool::FunctionCallError;
use crate::hollywood::identities;
use crate::hollywood::live_identity_matches_target;
use crate::rollout::find_thread_name_by_id;
use crate::session::session::Session;
use codex_protocol::ThreadId;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_path_uri::PathUri;
use std::path::Path;
use std::path::PathBuf;

#[derive(Debug, Default)]
pub(super) struct ApplyPatchCollaborationContext {
    matching_plans: Vec<codex_state::CollaborativeEditPlan>,
}

impl ApplyPatchCollaborationContext {
    pub(super) fn append_notice(&self, mut content: String) -> String {
        if self.matching_plans.is_empty() {
            return content;
        }

        content.push_str("\n\nCollaborative edit plan matched:");
        for plan in self.matching_plans.iter().take(5) {
            content.push_str("\n- ");
            content.push_str(plan.file_path.display().to_string().as_str());
            content.push_str(" :: ");
            content.push_str(plan.edit_slice.as_str());
            content.push_str(" (plan owner ");
            content.push_str(plan.actor_thread_id.as_str());
            content.push(')');
        }
        content.push_str(
            "\nAfter patching, send the planned Hollywood report-back with the exact slice changed and any merge risk.",
        );
        content
    }
}

#[derive(Clone)]
struct PeerPathClaimConflict {
    path: PathBuf,
    blocking_claim: codex_state::PathClaim,
    blocking_owner_identities: Vec<String>,
}

pub(super) async fn apply_patch_collaboration_preflight(
    session: &Session,
    file_paths: &[PathUri],
) -> Result<ApplyPatchCollaborationContext, FunctionCallError> {
    let Some(db) = session.state_db() else {
        return Ok(ApplyPatchCollaborationContext::default());
    };
    let native_file_paths = file_paths
        .iter()
        .filter_map(|path| path.to_abs_path().ok().map(AbsolutePathBuf::into_path_buf))
        .collect::<Vec<_>>();
    if native_file_paths.is_empty() {
        return Ok(ApplyPatchCollaborationContext::default());
    }

    let active_claims = match db.list_path_claims(/*owner_thread_id*/ None).await {
        Ok(claims) => claims,
        Err(err) => {
            tracing::warn!(%err, "skipping apply_patch collaborative edit preflight because path claims are unavailable");
            return Ok(ApplyPatchCollaborationContext::default());
        }
    };
    let actor_thread_id = session.thread_id();
    let actor_thread_name = session.thread_name().await;
    let actor_identities = identities(actor_thread_id, actor_thread_name.as_deref());
    let actor_thread_id_string = actor_thread_id.to_string();
    let mut peer_claim_conflicts = collect_peer_path_claim_conflicts(
        &native_file_paths,
        actor_thread_id_string.as_str(),
        &active_claims,
    );
    populate_blocking_owner_identities(session, &mut peer_claim_conflicts).await;
    let active_plans = match db
        .list_collaborative_edit_plans_for_files(&native_file_paths)
        .await
    {
        Ok(plans) => plans,
        Err(err) => {
            tracing::warn!(%err, "skipping apply_patch collaborative edit preflight because edit plans are unavailable");
            return Ok(ApplyPatchCollaborationContext::default());
        }
    };
    let matching_plans = active_plans
        .into_iter()
        .filter(|plan| {
            native_file_paths.iter().any(|path| {
                collaborative_edit_plan_allows_path(
                    plan,
                    actor_thread_id_string.as_str(),
                    &actor_identities,
                    path,
                )
            })
        })
        .collect::<Vec<_>>();

    let uncovered_conflicts = peer_claim_conflicts
        .iter()
        .filter(|conflict| {
            !matching_plans.iter().any(|plan| {
                collaborative_edit_plan_covers_conflict(
                    plan,
                    actor_thread_id_string.as_str(),
                    &actor_identities,
                    conflict,
                )
            })
        })
        .cloned()
        .collect::<Vec<_>>();
    if !uncovered_conflicts.is_empty() {
        return Err(FunctionCallError::RespondToModel(
            format_unplanned_peer_claim_conflicts(&uncovered_conflicts),
        ));
    }

    Ok(ApplyPatchCollaborationContext { matching_plans })
}

fn collect_peer_path_claim_conflicts(
    file_paths: &[PathBuf],
    actor_thread_id: &str,
    active_claims: &[codex_state::PathClaim],
) -> Vec<PeerPathClaimConflict> {
    let mut conflicts = Vec::new();
    for file_path in file_paths {
        for claim in active_claims {
            if claim.owner_thread_id == actor_thread_id {
                continue;
            }
            if path_claim_blocks_file(file_path.as_path(), claim) {
                conflicts.push(PeerPathClaimConflict {
                    path: file_path.clone(),
                    blocking_claim: claim.clone(),
                    blocking_owner_identities: Vec::new(),
                });
            }
        }
    }
    conflicts
}

fn path_claim_blocks_file(file_path: &Path, claim: &codex_state::PathClaim) -> bool {
    match claim.kind {
        codex_state::PathClaimKind::File => file_path == claim.path.as_path(),
        codex_state::PathClaimKind::Directory => {
            file_path == claim.path.as_path() || file_path.starts_with(claim.path.as_path())
        }
    }
}

async fn populate_blocking_owner_identities(
    session: &Session,
    conflicts: &mut [PeerPathClaimConflict],
) {
    let config = session.get_config().await;
    for conflict in conflicts {
        conflict.blocking_owner_identities = thread_identities(
            config.codex_home.as_path(),
            conflict.blocking_claim.owner_thread_id.as_str(),
        )
        .await;
    }
}

async fn thread_identities(codex_home: &Path, thread_id: &str) -> Vec<String> {
    let Ok(thread_id) = ThreadId::from_string(thread_id) else {
        return vec![thread_id.to_string()];
    };
    let thread_name = find_thread_name_by_id(codex_home, &thread_id)
        .await
        .ok()
        .flatten();
    identities(thread_id, thread_name.as_deref())
}

fn collaborative_edit_plan_allows_path(
    plan: &codex_state::CollaborativeEditPlan,
    actor_thread_id: &str,
    actor_identities: &[String],
    file_path: &Path,
) -> bool {
    plan.file_path == file_path
        && (plan.actor_thread_id == actor_thread_id
            || plan
                .peers
                .iter()
                .any(|peer| identity_matches_any(peer, actor_identities)))
}

fn collaborative_edit_plan_covers_conflict(
    plan: &codex_state::CollaborativeEditPlan,
    actor_thread_id: &str,
    actor_identities: &[String],
    conflict: &PeerPathClaimConflict,
) -> bool {
    let blocking_owner = conflict.blocking_claim.owner_thread_id.as_str();
    plan.file_path == conflict.path
        && ((plan.actor_thread_id == actor_thread_id
            && plan.peers.iter().any(|peer| {
                peer == blocking_owner
                    || identity_matches_any(peer, &conflict.blocking_owner_identities)
            }))
            || (plan.actor_thread_id == blocking_owner
                && plan.peers.iter().any(|peer| {
                    peer == actor_thread_id || identity_matches_any(peer, actor_identities)
                })))
}

fn identity_matches_any(value: &str, identities: &[String]) -> bool {
    identities.iter().any(|identity| {
        live_identity_matches_target(value, identity)
            || live_identity_matches_target(identity, value)
    })
}

fn format_unplanned_peer_claim_conflicts(conflicts: &[PeerPathClaimConflict]) -> String {
    let mut message = "apply_patch touches paths currently claimed by other Losangelex agents. Record a `collaborative_edit_plan` first, ask the owner to apply your proposed patch, or get a handoff/release before editing:\n".to_string();
    for conflict in conflicts.iter().take(8) {
        message.push_str("- ");
        message.push_str(conflict.path.display().to_string().as_str());
        message.push_str(" blocked by ");
        message.push_str(conflict.blocking_claim.kind.as_str());
        message.push_str(" claim owned by ");
        message.push_str(conflict.blocking_claim.owner_thread_id.as_str());
        message.push('\n');
    }
    message.push_str("A collaborative edit plan should name the file, slice/function/section, intended hunk, edit order or handoff, integrator, and report-back point. Re-read the current file and diff before retrying.");
    message
}
