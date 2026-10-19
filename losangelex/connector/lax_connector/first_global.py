"""First Global setup using LAX's existing native installation primitives.

No semantic scheduler lives here. Every persisted operation retains original
identities; repeating setup never starts a previously activated stopped agent.
"""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from . import collaboration_install, host, purpose_install
from .collaboration_capture import administrative_put
from .journal import saved
from .purpose_install import original, protected, file_once
from .purpose_readiness import require_sealed

SCHEMA = "lax-first-global-install/v1"


def start_once(root, unit):
    intent = root / (unit + ".start-intent.json")
    receipt = root / (unit + ".start-receipt.json")
    definition = Path("/etc/systemd/system") / unit
    expected = {"unit": unit, "definitionSha256": purpose_install.checksum(definition)}
    if intent.exists():
        if protected(intent) != expected:
            raise ValueError("Original infrastructure start definition changed")
        state = subprocess.check_output(["systemctl", "show", unit, "-p", "ActiveState", "--value"], text=True).strip()
        if not receipt.exists():
            if state != "active":
                raise RuntimeError("Original infrastructure activation is unconfirmed; inspect the same unit")
            saved(receipt, {**expected, "recoveredFromOriginalActiveUnit": True})
        return {"unit": unit, "state": state, "startRepeated": False}
    original(intent, expected)
    subprocess.run(["systemctl", "start", unit], check=True, capture_output=True)
    state = subprocess.check_output(["systemctl", "show", unit, "-p", "ActiveState", "--value"], text=True).strip()
    if state != "active":
        raise RuntimeError("Original infrastructure service did not become active")
    saved(receipt, {**expected, "recoveredFromOriginalActiveUnit": False})
    return {"unit": unit, "state": state, "startRepeated": False}


def provision(profile, *, activate=False):
    if os.geteuid() != 0:
        raise PermissionError("First Global installation requires the host administrator")
    if profile.get("schema") != SCHEMA:
        raise ValueError("Explicit native first-Global profile required")
    route = urlsplit(profile["hollywoodUrl"])
    if route.scheme != "http" or route.hostname not in ("127.0.0.1", "localhost", "::1") or route.username or route.password or route.query or route.fragment or route.path not in ("", "/"):
        raise ValueError("First-host bootstrap requires the actual same-host private Hollywood endpoint")
    installation = protected(Path(profile["installationIntent"]))
    authority = str(UUID(installation["authorityId"]))
    global_id = str(UUID(installation["credentials"]["Global"]["principalId"]))
    host_id = str(UUID(profile["hostId"]))
    base = Path("/var/lib/harness") / authority
    base.mkdir(mode=0o711, parents=True, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != 0:
        raise PermissionError("Native installation root differs")
    if (base / "global-admin-receipt.json").exists():
        raise ValueError("Existing single-context Global requires explicit adoption; first setup cannot replace it")
    root = base / "first-global"
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != 0:
        raise PermissionError("Native factory state is not administrator protected")
    digest = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
    original(root / "profile.json", {"digest": digest, "profile": profile})
    intent_path = root / "identity-intent.json"
    if not intent_path.exists():
        saved(intent_path, {"authorityId": authority, "agentId": global_id, "hostId": host_id,
            "workspaceId": str(uuid4()), "contextIds": {p: str(uuid4()) for p in purpose_install.PURPOSES},
            "tokens": {p: secrets.token_urlsafe(40) for p in purpose_install.PURPOSES}})
    identity = protected(intent_path)
    if (identity["authorityId"], identity["agentId"], identity["hostId"]) != (authority, global_id, host_id):
        raise ValueError("Original first-Global identity changed")
    owner = installation["credentials"]["Owner"]
    call = lambda method, path, value=None: host.request(profile["hollywoodUrl"], owner["token"], method, path, value)
    public = call("GET", "principals/" + global_id)
    if public["kind"] != "agent" or not public["administrator"] or public["authority"] != authority:
        raise PermissionError("Bootstrapped Global administrator identity required")
    ready_path = root / "ready.json"
    if ready_path.exists():
        ready = protected(ready_path)
        manifest = protected(purpose_install.directory(authority, global_id) / "installation.json")
        require_sealed(manifest)
        return {**ready, "reconciled": True, "activation": (
            purpose_install.activate(authority, global_id) if activate else {"requested": False}),
            "historicalAgentsResumed": False}
    for name in ("binary", "interpreter", "pythonRoot"):
        path = Path(profile[name])
        if not path.is_absolute() or any(not (c.isalnum() or c in "/_.-") for c in str(path)):
            raise ValueError("Literal installed native software paths required")
    administration = root / "administration"
    administration.mkdir(mode=0o700, exist_ok=True)
    administrative_put(root, call, "placements", {
        "operationId": "first-global-placement:" + authority, "hostId": host_id,
        "name": profile["hostName"], "identityFingerprint": host.machine_identity(),
        "capabilities": {"purposeNative": True, "workspaceRouting": "explicit-local", "model": profile["model"]},
        "agentId": global_id}, method="POST")
    enrollment_receipt = base / "hosts" / host_id / "enrollment-receipt.json"
    if enrollment_receipt.exists():
        enrollment = protected(enrollment_receipt)
        if enrollment["machineIdentity"] != host.machine_identity():
            raise ValueError("Original enrolled host identity differs")
    else:
        policy = {**profile["hostPolicy"], "controlAgentIds": [global_id]}
        enrollment = host.enroll({"authorityId": authority, "hostId": host_id,
            "hollywoodUrl": profile["hollywoodUrl"], "administratorCredential": owner, "policy": policy})
    controller_path = Path(enrollment["configPath"])
    admin_path = root / "collaboration-administrator.json"
    original(admin_path, {"authorityId": authority, "hostId": host_id,
                         "hollywoodUrl": profile["hollywoodUrl"], "token": owner["token"]})
    spec_path = root / "purpose-spec.json"
    channel = Path("/etc/harness") / authority / "collaboration" / host_id / "channel.json"
    spec = {**identity, "credential": installation["credentials"]["Global"]["token"],
        "global": True, "hollywoodUrl": profile["hollywoodUrl"], "machineIdentity": host.machine_identity(),
        **{k: profile[k] for k in ("binary", "interpreter", "pythonRoot", "model", "effort", "approvedModelAuthFile")},
        "nativeCollaborationChannel": str(channel)}
    for optional in ("environmentProfileFile", "serviceMemoryMaxBytes"):
        if optional in profile:
            spec[optional] = profile[optional]
    original(spec_path, spec)
    bindings = [{"purpose": p, "contextId": identity["contextIds"][p],
                 "credentialDigest": hashlib.sha256(json.dumps(identity["tokens"][p], sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
                for p in purpose_install.PURPOSES]
    administrative_put(root, call, "agents/" + global_id + "/context-system", {
        "operationId": "first-global-contexts:" + authority, "hostId": host_id,
        "workspaceId": identity["workspaceId"], "bindings": bindings})
    purpose_install.install(spec, prepare_only=True)
    manifest = protected(purpose_install.directory(authority, global_id) / "installation.json")
    config = protected(Path(manifest["config"]))
    setup = root / "collaboration-prepared"
    if not (setup / "setup.json").exists():
        collaboration_install.prepare({"schema": "lax-collaboration-install/v1",
            "controllerConfig": str(controller_path), "administratorConfig": str(admin_path),
            "interpreter": profile["interpreter"],
            "resources": [{"name": "global-private", "root": config["workspace"], "environmentId": "local"}],
            "agents": {global_id: {"resources": ["global-private"], "defaultResource": "global-private"}}}, setup)
    collaboration = collaboration_install.apply(setup)
    observer = "lax-host-" + authority.replace("-", "")[:8] + "-" + host_id.replace("-", "")[:8] + ".service"
    unit = ("[Unit]\nDescription=LAX native host observer " + host_id + "\nAfter=network-online.target\n"
        "[Service]\nType=simple\nUser=root\nExecStart=" + profile["interpreter"]
        + " -I -B -m lax_connector.host --serve " + str(controller_path)
        + "\nRestart=on-failure\nRestartSec=5\nMemoryMax=512M\nCPUQuota=50%\nUMask=0077\nKillMode=control-group\n")
    file_once(Path("/etc/systemd/system") / observer, unit)
    subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
    infrastructure = [start_once(root, observer), start_once(root, Path(collaboration["unitPath"]).name)]
    purpose_install.install(spec)
    from .linux_admin import ensure_supervision
    supervision = ensure_supervision(profile, installation, root)
    ready = {"schema": SCHEMA, "authorityId": authority, "agentId": global_id, "globalRoomId": installation["globalRoomId"],
        "hostId": host_id, "units": manifest["units"], "infrastructure": infrastructure,
        "phase": "sealed", "readinessFile": str(purpose_install.directory(authority, global_id) / "readiness.json"),
        "portfolioSupervision": supervision, "modelSubmissionByInstaller": False,
        "enterpriseInstallationComplete": False,
        "meaning": "Prepared and sealed native Global; actual first-user execution and lifecycle qualification remain required."}
    saved(ready_path, ready)
    return {**ready, "activation": purpose_install.activate(authority, global_id) if activate else {"requested": False}}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    print(json.dumps(provision(protected(args.spec), activate=args.activate)))


if __name__ == "__main__":
    main()

