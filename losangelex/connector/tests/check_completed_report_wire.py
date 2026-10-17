"""Validate real connector payload against exact reviewed server model classes.

Only selected class definitions are loaded from the supplied committed snapshot.
No server package, PostgreSQL, HTTP listener or native runtime is started.
"""
import argparse
import ast
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lax_connector import workflow
from test_completed_report_reconcile import Fixture


def models(path):
    source = path.read_bytes()
    tree = ast.parse(source, filename=str(path))
    names = {"Input", "WorkflowRevision", "ArtifactEvidence", "WorkReport", "WorkReportReconcile"}
    scope_path = path.with_name("report_scope_models.py")
    scope_source = scope_path.read_bytes()
    scope_tree = ast.parse(scope_source, filename=str(scope_path))
    proof = [n for n in scope_tree.body if isinstance(n, ast.ClassDef) and n.name == "ReportScopeProof"]
    if len(proof) != 1:
        raise ValueError("Reviewed scoped proof model missing")
    selected = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in names]
    if {n.name for n in selected} != names:
        raise ValueError("Reviewed server model definitions differ")
    namespace = {"__name__": __name__, "BaseModel": BaseModel, "ConfigDict": ConfigDict,
                 "Field": Field, "Literal": Literal, "UUID": UUID}
    namespace["SHA"] = r"^[a-f0-9]{64}$"
    # Dependencies are loaded in source order from the two exact snapshots only.
    selected.insert(next(i for i,n in enumerate(selected) if n.name == "WorkReportReconcile"), proof[0])
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    namespace["scopeSourceSha256"] = hashlib.sha256(scope_source).hexdigest()
    route = any(isinstance(n, ast.Dict) and any(
        isinstance(k, ast.Constant) and k.value == "report-reconcile"
        and isinstance(v, ast.Name) and v.id == "WorkReportReconcile"
        for k, v in zip(n.keys, n.values)) for n in ast.walk(tree))
    if not route:
        raise ValueError("Reviewed route does not select the reconciliation model")
    return namespace, hashlib.sha256(source).hexdigest()


async def check(path):
    ns, sha = models(path)
    model = ns["WorkReportReconcile"]
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        c = Fixture(Path(tmp))
        await workflow.invoke(c, "hollywood_work_report_reconcile", c.args, "wire-fixture")
        payload = c.posts()[0][2]
        model.model_validate(payload)
        assert set(payload) == {"operationId", "revision", "priorDeliveryId", "state",
                                "effectDisposition", "note", "evidence", "briefingSequence", "scopeRead"}
        checks.append("Actual connector submitted/reviewed body accepted by exact pinned server model")
        for extra in ["currentDeliveryId", "currentClaimId", "currentGeneration", "claimId", "contextId"]:
            try:
                model.model_validate({**payload, extra: "forbidden-caller-hint"})
            except ValidationError:
                pass
            else:
                raise AssertionError(extra)
        checks.append("Superseded current identity/body hints rejected by actual extra-forbid model")
        for name in ("effectDisposition", "priorDeliveryId", "scopeRead"):
            try:
                model.model_validate({k: v for k, v in payload.items() if k != name})
            except ValidationError:
                pass
            else:
                raise AssertionError(name)
        checks.append("Explicit attestation and original-delivery fields are mandatory")
        await workflow.invoke(c, "hollywood_work_report_reconcile",
            {**c.args, "state": "blocked", "effectDisposition": "unknown", "artifactPaths": []}, "blocked-wire-fixture")
        blocked = c.posts()[-1][2]
        model.model_validate(blocked)
        assert blocked["effectDisposition"] == "unknown"
        checks.append("Actual connector blocked/unknown body is preserved and schema-compatible")
        try:
            ns["WorkReport"].model_validate(payload)
        except ValidationError:
            pass
        else:
            raise AssertionError("Ordinary report must remain a different strict wire")
        checks.append("Ordinary report model rejects reconciliation body")
    return {"passed": True, "serverSource": str(path), "serverSourceSha256": sha, "scopeSourceSha256": ns["scopeSourceSha256"],
            "checks": checks, "actualHTTP": False, "actualPostgreSQL": False, "nativeModelTurns": 0,
            "scope": "Exact selected model compatibility only; no domain authority/SQL proof"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-source", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(check(args.server_source)), indent=2))
