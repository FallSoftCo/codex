use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn policy_requires_explicit_binding_and_rejects_unknown_authority() {
    let policy = json!({"type":"canonical","contextId":"context","purpose":"writer"});
    assert_eq!(
        serde_json::from_value::<AutomaticContextRefillPolicy>(policy.clone()).unwrap(),
        AutomaticContextRefillPolicy::Canonical {
            context_id: "context".to_owned(),
            purpose: ContextRefillPurpose::Writer,
        }
    );
    for invalid in [
        json!({"type":"canonical","purpose":"writer"}),
        json!({"type":"canonical","contextId":"context","purpose":"root"}),
        json!({"type":"canonical","contextId":"context","purpose":"writer","permitId":"forged"}),
    ] {
        assert!(serde_json::from_value::<AutomaticContextRefillPolicy>(invalid).is_err());
    }
    assert_eq!(
        serde_json::to_value(
            serde_json::from_value::<AutomaticContextRefillPolicy>(policy).unwrap()
        )
        .unwrap(),
        json!({"type":"canonical","contextId":"context","purpose":"writer"})
    );
}

#[test]
fn installed_cut_is_required_and_round_trips_without_raw_items() {
    let receipt = json!({
        "threadId":"thread", "turnId":"turn", "operationId":"op",
        "contextId":"context", "purpose":"writer",
        "snapshotOperationId":"snapshot", "snapshotReadPoint":"read-point",
        "snapshotSha256":"digest", "nativeActionsSha256":"actions",
        "selectionRevision":3, "totalBytes":5,
        "previousWindowId":"old", "windowId":"new",
        "nativeHistoryBytes":999, "nativeHistorySha256":"history"
    });
    let decoded: ContextWindowInstalledParams = serde_json::from_value(receipt.clone()).unwrap();
    assert_eq!(serde_json::to_value(decoded).unwrap(), receipt);
    for missing in [
        "snapshotReadPoint",
        "totalBytes",
        "turnId",
        "nativeHistorySha256",
    ] {
        let mut invalid = receipt.clone();
        invalid.as_object_mut().unwrap().remove(missing);
        assert!(serde_json::from_value::<ContextWindowInstalledParams>(invalid).is_err());
    }
    let mut extra = receipt;
    extra["items"] = json!([]);
    assert!(serde_json::from_value::<ContextWindowInstalledParams>(extra).is_err());
}
