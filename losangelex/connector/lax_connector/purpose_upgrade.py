"""Offline connector/profile upgrade for one installed three-context identity.

The operator pauses its canonical placement and drains/stops all three services
first. This command neither pauses admission nor stops/starts services. It keeps
the original installation intent, histories, credentials and work. Native images switch only to an explicitly
selected immutable package with its expected executable hash.
An interrupted publication requires inspecting the original receipt or explicit
offline rollback; it is never automatically replayed.
"""
import argparse
import base64
import fcntl
import json
import os
import stat
import subprocess
from pathlib import Path
from uuid import UUID

from . import purpose_install as install, service_observer as observer
from .host import request
from .journal import saved
from .native_image_upgrade import registry_lock

SCHEMA = "lax-purpose-upgrade/v1"


def offline(value, config):
    for unit in value["units"].values():
        info = observer.properties(unit)
        if info["ActiveState"] != "inactive" or int(info["MainPID"]) != 0:
            raise ValueError("All owned purpose services must already be stopped")
        if info["ControlGroup"] and observer.members(info["ControlGroup"]):
            raise ValueError("Original purpose descendants remain")
    spec = install.protected(install.directory(value["authorityId"], value["agentId"]) / "intent.json")["spec"]
    row = request(config["hollywoodUrl"], spec["credential"], "GET",
                  "placements/" + value["agentId"])
    if row["state"] != "paused" or row["hostId"] != value["hostId"]:
        raise ValueError("Same enrolled placement must remain paused")
    original = install.canonical(spec, config)
    histories = {}
    for purpose in install.PURPOSES:
        state = Path(config["state"]) / purpose
        wake = json.loads((state / "wake.json").read_text()) if (state / "wake.json").exists() else {}
        if wake.get("state") in ("submission_intent", "running", "unknown"):
            raise ValueError("Original native submission remains unsettled")
        histories[purpose] = install.checksum(state / "context.json")
    return {"placementRevision": row["placement"]["revision"], "canonical": original,
            "historyFiles": histories}


def publish(path, data, mode, gid):
    # Existing atomic, fsync-backed publication; original bytes are retained.
    from .journal import _sync
    import tempfile
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, gid)
            os.fsync(stream.fileno())
        os.replace(name, path)
        _sync(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def encoded(path):
    path = Path(path)
    info = path.lstat()
    if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
        raise PermissionError("Upgrade target is not administrator protected")
    return {"path": str(path), "data": base64.b64encode(path.read_bytes()).decode(),
            "mode": info.st_mode & 0o777, "gid": info.st_gid}


def apply(item):
    publish(item["path"], base64.b64decode(item["data"]), item["mode"], item["gid"])


def stage(path, value, *, mode=None, gid=None):
    old = encoded(path)
    data = (json.dumps(value, indent=2) + "\n").encode() if isinstance(value, dict) else value
    return {**old, "data": base64.b64encode(data).decode(),
            "mode": old["mode"] if mode is None else mode,
            "gid": old["gid"] if gid is None else gid}


def upgrade(spec):
    if os.geteuid() != 0:
        raise PermissionError("Installation administrator required")
    if set(spec) - {"schema", "operationId", "authorityId", "agentId",
                    "expectedInstallationSha256", "interpreter", "pythonRoot", "toolProfileFile",
                    "binary", "expectedBinarySha256"}:
        raise ValueError("Unsupported purpose upgrade field")
    if spec["schema"] != SCHEMA:
        raise ValueError("Explicit purpose upgrade required")
    if ("binary" in spec) != ("expectedBinarySha256" in spec):
        raise ValueError("Native image path and expected SHA256 must be supplied together")
    if "binary" in spec:
        digest = spec["expectedBinarySha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Explicit native executable SHA256 required")
    operation = str(UUID(spec["operationId"]))
    record = install.directory(spec["authorityId"], spec["agentId"])
    with registry_lock(record):
        manifest_path = record / "installation.json"
        value = install.protected(manifest_path)
        config = install.protected(value["config"])
        intent_path = record / ("upgrade-" + operation + ".json")
        if intent_path.exists():
            raise ValueError("Original upgrade exists; inspect its status, do not replay")
        pointer = record / "current-upgrade.json"
        if pointer.exists() and install.protected(pointer)["state"] == "intent":
            raise ValueError("Original interrupted upgrade needs explicit reconciliation")
        if install.checksum(manifest_path) != spec["expectedInstallationSha256"]:
            raise ValueError("Installation revision changed")
        from .purpose_readiness import require_sealed, verify
        require_sealed(value)
        # Exclusive with both the aggregate and separate purpose launchers.
        lock = os.open(Path(config["state"]) / "agent.lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = offline(value, config)
            root = Path(spec["pythonRoot"]).resolve(strict=True)
            interpreter = Path(spec["interpreter"])
            if (not root.is_absolute() or root.stat().st_uid != 0 or root.stat().st_mode & 0o022
                    or not interpreter.is_relative_to(root)):
                raise PermissionError("Protected explicit runtime required")
            runtime = json.loads(subprocess.check_output(
                ["runuser", "-u", value["linuxUser"], "--", str(interpreter), "-I", "-B", "-c",
                 "import json,sys,lax_connector.context_runtime as c;print(json.dumps({'module':c.__file__,'prefix':sys.prefix}))"],
                text=True))
            if not Path(runtime["module"]).is_relative_to(root) or runtime["prefix"] != str(root):
                raise ValueError("Installed interpreter loads another connector")
            binary = Path(spec.get("binary", value["binary"]))
            if not binary.is_absolute():
                raise PermissionError("Explicit absolute native image path required")
            binary = binary.resolve(strict=True)
            from .native_package import preflight_as_owner
            package = preflight_as_owner(str(binary), str(interpreter), value["uid"],
                                         Path(value["home"]), workspace=config["workspace"])
            if "binary" in spec:
                if package["assets"]["entrypoint"]["sha256"] != spec["expectedBinarySha256"]:
                    raise ValueError("Selected native executable differs from expected SHA256")
                paths = [Path(asset["path"]) for asset in package["assets"].values()]
                paths.append(Path(package["packageRoot"]) / "codex-package.json")
                for path in paths:
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                        raise PermissionError("Native package must be administrator-owned and protected")
                for path in binary.parents:
                    info = path.stat()
                    if info.st_uid != 0 or info.st_mode & 0o022:
                        raise PermissionError("Native package parent is not protected")
            image = binary.stat()
            updated = {**config, "pythonRoot": str(root), "binary": str(binary)}
            if "toolProfileFile" in spec:
                from .tool_profile import read
                source = Path(spec["toolProfileFile"])
                profile = read(source)
                target = record / ("tool-profile-" + profile["sha256"] + ".json")
                install.file_once(target, source.read_text(), 0o440)
                os.chown(target, 0, value["gid"])
                read(target, profile["sha256"])
                updated.update(toolProfileFile=str(target), toolProfileSha256=profile["sha256"])
            changes = [stage(value["config"], updated)]
            definitions = {}
            for unit in value["units"].values():
                path = Path("/etc/systemd/system") / unit
                old = path.read_text()
                expected = "ExecStart=" + value["interpreter"] + " -m lax_connector.context_runtime"
                replacement = "ExecStart=" + str(interpreter) + " -m lax_connector.context_runtime"
                if old.count(expected) != 1:
                    raise ValueError("Owned service launcher differs")
                text = old.replace(expected, replacement).encode()
                changes.append(stage(path, text))
                import hashlib
                definitions[unit] = hashlib.sha256(text).hexdigest()
            import hashlib
            new_value = {**value, "binary": str(binary), "binaryDevice": image.st_dev,
                         "binaryInode": image.st_ino, "configSha256": hashlib.sha256(base64.b64decode(changes[0]["data"])).hexdigest(),
                         "interpreter": str(interpreter), "pythonRoot": str(root), "runtime": runtime,
                         "unitDefinitionDigests": definitions, "nativePackage": package}
            changes.append(stage(manifest_path, new_value))
            paths = [Path(i["path"]) for i in changes] + [record / "readiness.json"]
            receipt = {"schema": SCHEMA, "operationId": operation, "state": "intent",
                       "before": [encoded(p) for p in paths], "after": changes,
                       "beforeOffline": before, "servicesStarted": 0, "modelsStarted": 0,
                       "nativeBinaryChanged": str(binary) != value["binary"], "identitiesReplaced": False}
            if offline(value, config) != before:
                raise ValueError("Original state changed before upgrade")
            saved(intent_path, receipt)
            saved(pointer, receipt)
            for item in changes:
                apply(item)
            subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
            if offline(new_value, updated) != before:
                raise ValueError("Original histories or canonical state changed")
            readiness = verify(new_value)
            saved(record / "readiness.json", readiness)
            receipt = {**receipt, "state": "accepted",
                       "acceptedInstallationSha256": install.checksum(manifest_path),
                       "identityAndHistoryPreserved": True}
            saved(intent_path, receipt)
            saved(pointer, receipt)
            return {"schema": SCHEMA, "operationId": operation, "state": "accepted",
                    "installationSha256": receipt["acceptedInstallationSha256"],
                    "servicesStarted": 0, "modelsStarted": 0,
                    "identityAndHistoryPreserved": True}
        finally:
            os.close(lock)


def rollback(authority, agent, operation, expected_installation):
    if os.geteuid() != 0:
        raise PermissionError("Installation administrator required")
    record = install.directory(authority, agent)
    operation = str(UUID(operation))
    with registry_lock(record):
        path = record / ("upgrade-" + operation + ".json")
        receipt = install.protected(path)
        if receipt["state"] not in ("intent", "accepted"):
            raise ValueError("Original upgrade already settled differently")
        manifest = record / "installation.json"
        if install.checksum(manifest) != expected_installation:
            raise ValueError("Inspect the actual installation before rollback")
        before = {i["path"]: i for i in receipt["before"]}
        old_value = json.loads(base64.b64decode(before[str(manifest)]["data"]))
        old_config = json.loads(base64.b64decode(before[old_value["config"]]["data"]))
        lock = os.open(Path(old_config["state"]) / "agent.lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            current = offline(old_value, old_config)
            if {k:v for k,v in current.items() if k != "placementRevision"} != {k:v for k,v in receipt["beforeOffline"].items() if k != "placementRevision"}:
                raise ValueError("Original offline scope changed")
            for item in receipt["before"]:
                current = encoded(item["path"])
                allowed = [x for x in receipt["before"] + receipt["after"] if x["path"] == item["path"]]
                if not any(current == x for x in allowed) and item["path"] != str(record / "readiness.json"):
                    raise ValueError("Upgrade target changed outside original transition")
            for item in receipt["before"]:
                apply(item)
            subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
            from .purpose_readiness import require_sealed
            require_sealed(old_value)
            receipt = {**receipt, "state": "rolled_back"}
            saved(path, receipt)
            saved(record / "current-upgrade.json", receipt)
            return {"state": "rolled_back", "servicesStarted": 0, "modelsStarted": 0,
                    "workOrDatabaseReverted": False}
        finally:
            os.close(lock)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--rollback", action="store_true")
    args = p.parse_args()
    spec = install.protected(args.spec)
    if args.rollback:
        result = rollback(spec["authorityId"], spec["agentId"], spec["operationId"],
                          spec["expectedInstallationSha256"])
    else:
        result = upgrade(spec)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
