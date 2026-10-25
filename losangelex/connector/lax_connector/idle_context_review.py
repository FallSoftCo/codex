"""Sealed native preparation; caller authorization belongs to Hollywood controls."""
import hashlib
import json
from pathlib import Path

from .automatic_refill_data import require
from .automatic_refill_recovery import connection

FIELDS = ("operationId", "requestOperationId", "snapshotOperationId", "installedOperationId",
          "nativeThread", "agentId", "contextId", "purpose", "originalHistory", "request",
          "response", "preflight", "retainedBudget", "snapshot", "preparedConfigSha256",
          "preparedCapabilities", "preparedRuntime")
OUTCOMES = ("nativeDispatchIntent", "installed", "hostReceipt", "nativeResult", "nativeRejection")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def config_digest(runner):
    return digest(runner.config)


def runtime_identity(runner):
    result = {}
    for key, path in (("binarySha256", Path(runner.rpc.binary)),
                      ("homeConfigSha256", runner.rpc.home / "config.toml")):
        if not path.exists():
            result[key] = None
            continue
        hashed = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hashed.update(block)
        result[key] = hashed.hexdigest()
    return result


def manifest(operation):
    return {key: operation[key] for key in FIELDS}


def seal(owner, operation):
    require(operation.get("reviewMode") == "manual", "Explicit review preparation required")
    operation["preparedConfigSha256"] = config_digest(owner.runner)
    operation["preparedCapabilities"] = sorted(owner.runner.rpc.lax_capabilities)
    operation["preparedRuntime"] = runtime_identity(owner.runner)
    operation["approvalDigest"] = digest(manifest(operation))
    owner.save(operation, "review_prepared")


def check_seal(owner, operation):
    r = owner.runner
    require(operation.get("reviewMode") == "manual"
            and operation.get("state") == "review_prepared"
            and not any(key in operation for key in OUTCOMES)
            and all(operation[key] == value for key, value in (
                ("agentId", r.config["agentId"]), ("contextId", r.config["contextIds"][r.purpose]),
                ("purpose", r.purpose), ("nativeThread", r.thread)))
            and digest(manifest(operation)) == operation.get("approvalDigest"),
            "Original prepared review or no-dispatch proof changed")


def approve(owner, operation, approved_digest):
    check_seal(owner, operation)
    require(approved_digest == operation["approvalDigest"],
            "Exact reviewed native preparation approval required")
    require(config_digest(owner.runner) == operation["preparedConfigSha256"]
            and sorted(owner.runner.rpc.lax_capabilities) == operation["preparedCapabilities"]
            and runtime_identity(owner.runner) == operation["preparedRuntime"],
            "Native configuration changed since review")


def restore(owner, operation):
    check_seal(owner, operation)
    require(owner.pending is None, "Multiple native reviews cannot own one purpose")
    owner.pending = operation
    owner.epoch = connection(owner.runner)


async def cancel(owner, operation):
    async with owner.runner.effect_lock:
        owner.check(operation)
        check_seal(owner, operation)
        owner.save(operation, "review_cancelled")
        owner.pending = None
        owner.epoch = None
        return {"operationId": operation["operationId"], "state": "review_cancelled",
                "nativeWindowChanged": False}


def cancelled(operation):
    require(operation.get("reviewMode") == "manual"
            and operation.get("state") == "review_cancelled"
            and not any(key in operation for key in OUTCOMES)
            and digest(manifest(operation)) == operation.get("approvalDigest"),
            "Cancelled native review has dispatched or changed provenance")
